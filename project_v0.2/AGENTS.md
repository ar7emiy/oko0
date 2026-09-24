# AGENTS.md

## Purpose

Build the system described in [ARCHITECTURE.md](ARCHITECTURE.md). The first user journey is import text, inspect a mention, open its provisional dossier, inspect the resolution evidence, and correct an attribution without losing history.

## Implementation rules

1. Preserve original source versions. Code assigns durable IDs and exact evidence boundaries. Never replace evidence with normalized or model-rewritten text.
2. A mention is not an entity. Pronouns, descriptions, identifiers, and unresolved references are stored occurrences.
3. Models propose semantic interpretations. Code validates structure, grounds evidence, persists decisions, and controls which actions can be committed.
4. Keep source statements, attributed statements, and real-world verification separate. Preserve negation, reported speech, uncertainty, and unknown dates.
5. Identity is never asserted without its evidence. Every identity link carries a score and a basis (identifier, name-only, contextual, or combinations). Name-only links are first-class and visible, never silently upgraded. Merged views are read-time projections at a declared confidence level, showing each member's link and the weakest link. Conflicting identifiers veto. Role-based priors are optional domain rules that declare their semantics.
6. Keep cross-document identity acceptance off by default. Local machine selections may populate visibly provisional dossiers. Users may inspect and revise decisions.
7. Human decisions are superseded explicitly, never silently overwritten by a rerun. Stable entity handles survive new mentions; splits and consolidations preserve lineage.
8. Dossiers and graphs are projections of the same source/decision revision. Neither may invent a semantic relationship at rendering time.
9. Start with one relational store and one general model adapter. Do not add model ensembles, vector services, registries, or a graph engine before a concrete decision card justifies them.
10. Claim-specific roles, metadata, and identifier rules belong in optional adapters. Unknown types/predicates remain representable. Do not make English name shape a persistence gate.
11. Every gate has an unresolved outcome. Failed processing is not “nothing found.” Rejected grounding remains diagnostic and cannot be promoted into a sourced fact.
12. Do not use the predecessor's accuracy metrics to justify architecture. New evaluation uses independently annotated data, frozen definitions, and explicit denominators.
13. Keep ground-truth/test labels outside runtime inputs. Never tune prompts, policies, or thresholds on the sealed test set.

## Change control

Before expanding a gate, add a short decision card stating the user need, new permitted decision, retained evidence/dependencies, unresolved outcome, dossier effect, and how to disable/reverse it. Prefer one gate change per implementation increment. This is documentation discipline, not an automatic requirement to interrupt the user for permission.

## Conventions

Python library code in `src/`, orchestration in plain `.py` files if needed. Introduce one central runtime configuration when implementation starts. No model names or arbitrary decision thresholds scattered through consumers. Implement ordinary constraints and repeat-safe writes before derived stores.

Update `STATE.md` with implemented behavior and actual checks; distinguish proposals, executable features, and deferred capabilities. Do not claim a runtime exists merely because its design or schema is written.
