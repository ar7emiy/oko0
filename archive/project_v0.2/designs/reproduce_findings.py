"""Bounded audit probes: source files only; no corpus, project imports, or APIs.

Run from any directory with Python 3.10+. Selected original function/class ASTs
execute with explicit standard-library dependencies. These are counterexamples,
not a substitute for integration tests or corpus accuracy measurements.
"""
import ast
import dataclasses
import json
import re
import sqlite3
import types
import uuid
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def selected(path, names, env=None):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        defined = {node.name} if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else set()
        if isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        if defined & set(names):
            nodes.append(node)
    scope = dict(globals())
    scope.update(env or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, "exec"), scope)
    return scope


def run():
    results = {}
    ner = selected("project_v0.1/src/ner_ensemble.py",
                   ["SpanCandidate", "_locate", "_parse_llm_spans", "_overlaps", "union_spans"],
                   {"dataclass": dataclasses.dataclass, "field": dataclasses.field,
                    "coref": types.SimpleNamespace(is_anaphor=lambda _: False)})
    raw = "Jane\n  Smith called."
    row = ner["_parse_llm_spans"]({"entities": [{"text": "Jane Smith", "start": 0}]}, raw, 0)[0]
    results["span_whitespace"] = {"stored": row.text, "actual": raw[row.start:row.end],
                                   "exact": row.text == raw[row.start:row.end]}
    raw = "Jane called. Jane replied."
    rows = ner["_parse_llm_spans"]({"entities": [{"text": "Jane"}, {"text": "Jane"}]}, raw, 0)
    results["repeated_quote"] = {"positions": [r.start for r in rows], "expected_occurrences": [0, 13]}
    candidate = ner["SpanCandidate"]
    rows = ner["union_spans"]([[candidate(0, 10, "Jane Smith", "person", {"ner"}),
                                 candidate(0, 21, "Jane Smith Foundation", "organization", {"llm"})]])
    results["nested_span"] = [{"text": r.text, "label": r.label, "extractors": sorted(r.extractors)} for r in rows]

    typing = selected("project_v0.1/src/entity_type.py", ["_LEGAL_FORMS", "_PERSON_TITLES",
                      "_PERSON_SUFFIXES", "_SEED_HEAD_NOUNS", "_WORD", "_tokens", "learn_head_nouns", "entity_type"])
    names = ["Alder Clinic", "Birch Clinic", "Cedar Clinic"]
    before = typing["learn_head_nouns"](names)
    after = typing["learn_head_nouns"](names + ["Clinic Partners"])
    results["typing_corpus_change"] = {"before": typing["entity_type"]("Alder Clinic", before),
                                        "after": typing["entity_type"]("Alder Clinic", after)}
    results["typing_legal_form"] = typing["entity_type"]("Dr. Jane Smith LLC")

    cfg = types.SimpleNamespace(COREF_PRONOUNS=("he", "she", "it", "they"),
                                COREF_DESCRIPTORS=("the claimant",), COREF_MAX_ANTECEDENT_CHARS=600)
    coref = selected("project_v0.1/src/coref.py", ["CorefLink", "_MASC", "_FEM", "_PLUR", "_NEUT",
                     "_PERSON_PRONOUNS", "_ORG_PRONOUNS", "_DESCRIPTOR_TYPE", "descriptor_type",
                     "CorefResolver", "RuleBasedCorefResolver"], {"CFG": cfg, "dataclass": dataclasses.dataclass})
    resolver = coref["RuleBasedCorefResolver"]()
    raw = "Jane spoke to Mary. She confirmed the address."
    mentions = [{"start": 0, "end": 4, "text": "Jane", "entity_type": "person"},
                {"start": 14, "end": 18, "text": "Mary", "entity_type": "person"}]
    results["ambiguous_coreference"] = [dataclasses.asdict(r) for r in resolver.resolve(raw, mentions)]
    results["unresolved_pronoun"] = len(resolver.resolve("She called.", []))
    raw = "The sedan stalled. It stopped."
    results["vehicle_pronoun"] = len(resolver.resolve(raw,
        [{"start": 4, "end": 9, "text": "sedan", "entity_type": "vehicle"}]))

    schema = selected("project_v0.1/src/contracts.py", ["DDL"])
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(schema["DDL"])
    db.execute("INSERT INTO identity_link(link_id,local_id_a,local_id_b,basis,status) VALUES('l','missing-a','missing-b','invented','accepted')")
    db.execute("UPDATE identity_link SET status='auto' WHERE link_id='l'")
    results["ddl_human_decision_enforcement"] = {"dangling_endpoints_accepted": True,
                                                "accepted_status_after_update": db.execute("SELECT status FROM identity_link").fetchone()[0]}

    cfg = types.SimpleNamespace(SURVIVORSHIP_TIERS={"validated_id": 3, "template_field": 2, "narrative": 1})
    prof = selected("project/src/profiles.py", ["IDENTIFIER_ATTRS", "SNIPPET_PAD", "_tier",
                    "render_assertion_annotation", "_evidence_item", "_build_attributes"], {"CFG": cfg})
    base = {"predicate": "has_phone", "extractor": "gazetteer", "object_value_raw": "5550100",
            "object_value_norm": "5550100", "grounded": 1, "source_doc_id": "invented",
            "source_span_start": 0, "source_span_end": 7, "pass_id": "probe"}
    assertions = [{**base, "assertion_id": "old", "polarity": "negated", "recorded_date": "2020-01-01"},
                  {**base, "assertion_id": "new", "polarity": "asserted", "recorded_date": "2026-01-01"}]
    attrs = []
    timelines, _, _ = prof["_build_attributes"]("E", assertions, {"invented": "5550100"}, attrs)
    results["dossier_reassertion"] = {"timeline": timelines, "known_from": attrs[0]["known_from"]}
    results["normalized_phone_tier"] = prof["_tier"](base)
    return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
