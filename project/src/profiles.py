"""Notebook 06 engine: bitemporal entity profiles + verifiable dossiers.

For each resolved entity:
  - Bitemporal attribute rows (valid_from/valid_to real-world window;
    known_from/known_to system-knowledge window) computed from grounded
    assertions with survivorship tiers (validated-ID > template field >
    narrative; recency only WITHIN a tier). Retractions/negations close
    known_to. Conflicting surviving values are flagged, never hidden.
  - A dossier JSON: identity summary, attribute timelines, roles per claim,
    allegations SEGREGATED from facts, linked entities (shared identifiers/
    addresses with degree context), and an EVIDENCE LIST where every item is
    {doc_id, span, snippet, machine_annotation}.

machine_annotation is RENDERED FROM STORED DATA ONLY -- a deterministic template
over the assertion's predicate/polarity/dates and, for resolution edges, the
stored gen_passes + feature weights + adjudicator rationale. No free-generated
prose at display time: the annotation exists to let a user verify WHY an edge or
fact is present, so it must be reproducible from the tables.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict

from . import contracts, textnorm
from .repository import Repository
from .settings import CFG, Paths

IDENTIFIER_ATTRS = {"has_email", "has_phone", "has_npi", "has_tin", "has_ssn"}
CLASS_ROLE = {
    "claimant": "claimant", "attorney": "claimant_attorney",
    "medical_provider": "treating_provider", "repair_shop": "repair_shop",
    "adjuster": "adjuster",
}
SNIPPET_PAD = 45


def _tier(assertion) -> str:
    p = assertion["predicate"]
    if p in IDENTIFIER_ATTRS and assertion["extractor"] == "template":
        return "validated_id"
    if p in IDENTIFIER_ATTRS and assertion["object_value_norm"]:
        # validated identifiers from narrative still rank as validated_id
        if p == "has_npi" and not textnorm.npi_is_valid(assertion["object_value_norm"]):
            return "narrative"
        return "validated_id"
    if assertion["extractor"] == "template":
        return "template_field"
    return "narrative"


def render_assertion_annotation(a) -> str:
    """Deterministic template over stored assertion fields (verification string)."""
    parts = [f"{a['polarity']} {a['predicate']}"]
    if a["object_value_raw"]:
        parts.append(f"= {a['object_value_raw']}")
    tier = _tier(a)
    parts.append(f"[tier={tier}, extractor={a['extractor']}, pass={a['pass_id']}]")
    if a.get("effective_from"):
        parts.append(f"effective {a['effective_from']}" + (f"..{a['effective_to']}" if a.get("effective_to") else ""))
    parts.append(f"src {a['source_doc_id']}[{a['source_span_start']}:{a['source_span_end']}]")
    if not a["grounded"]:
        parts.append("(UNGROUNDED)")
    return " ".join(parts)


def render_link_annotation(shared_key: str, pair_row: dict | None) -> str:
    """Deterministic link explanation from the stored resolution edge.

    Reads `same_as_edges` (Splink output): a calibrated probability plus the
    blocking/​suppression context. There is no adjudicator verdict any more --
    identity is threshold-derived, so the honest annotation is the probability
    and whether the edge was suppressed before clustering.
    """
    if pair_row is None:
        return f"Linked via {shared_key} (shared attribute; no scored resolution edge)."
    bits = [f"shared {shared_key}"]
    prob = pair_row.get("probability")
    if prob is not None:
        bits.append(f"match probability {float(prob):.3f}")
    mw = pair_row.get("match_weight")
    if mw is not None:
        bits.append(f"match weight {float(mw):+.2f}")
    backend = pair_row.get("backend")
    if backend:
        bits.append(f"backend {backend}")
    ann = "Linked via: " + "; ".join(bits)
    supp = pair_row.get("suppressed_reason")
    if supp:
        ann += f" [edge SUPPRESSED before clustering: {supp}]"
    return ann

def run(repo: Repository) -> dict:
    texts = {f.stem: f.read_text() for f in Paths.raw_notes.glob("*.txt")}
    members = repo.table("entity_members")
    entities = repo.table("entities").set_index("entity_id")
    mentions = repo.table("mentions").set_index("mention_id")
    assertions = repo.table("assertions")
    docs = repo.table("documents").set_index("doc_id")["claim_id"].to_dict()

    ass_by_subj = defaultdict(list)
    for _, a in assertions.iterrows():
        ass_by_subj[a["subject_mention_id"]].append(a.to_dict())

    ent_to_mentions = defaultdict(list)
    for _, r in members.iterrows():
        ent_to_mentions[r["entity_id"]].append(r["mention_id"])

    # identifier/address -> entities (for linked-entity discovery)
    id_index = defaultdict(set)
    ent_identifiers = defaultdict(lambda: defaultdict(set))
    for eid, mids in ent_to_mentions.items():
        for mid in mids:
            for a in ass_by_subj.get(mid, []):
                if a["grounded"] != 1 or a["polarity"] in ("negated", "retracted"):
                    continue
                p = a["predicate"]
                if p in IDENTIFIER_ATTRS:
                    key = (p, a["object_value_norm"])
                    id_index[key].add(eid)
                    ent_identifiers[eid][p].add(a["object_value_norm"])
                elif p == "has_address":
                    key = ("addr", textnorm.address_key(a["object_value_raw"] or ""))
                    if key[1]:
                        id_index[key].add(eid)
                        ent_identifiers[eid]["addr"].add(key[1])
                elif p == "has_email":
                    dom = textnorm.email_domain(a["object_value_norm"] or "")
                    if dom:
                        ent_identifiers[eid]["email_domain"].add(dom)

    # resolution edges indexed by (mention_a, mention_b) for link annotations.
    # v2: probabilistic same_as_edges, not the retired adjudicated candidate_pairs.
    cp = repo.table("same_as_edges")
    pair_by_mentions = {}
    for _, r in cp.iterrows():
        pair_by_mentions[frozenset((r["mention_id_a"], r["mention_id_b"]))] = r.to_dict()

    attr_rows = []
    dossiers = 0
    for eid, mids in ent_to_mentions.items():
        ent = entities.loc[eid]
        # collect assertions
        ent_assertions = []
        for mid in mids:
            ent_assertions.extend(ass_by_subj.get(mid, []))
        grounded = [a for a in ent_assertions if a["grounded"] == 1]

        timelines, evidence, allegations = _build_attributes(
            eid, grounded, texts, attr_rows)
        roles = _roles_per_claim(mids, mentions, docs)
        linked = _linked_entities(eid, ent_identifiers, id_index, ent_to_mentions,
                                  pair_by_mentions, entities)

        dossier = {
            "entity_id": eid,
            "class": ent["entity_class"],
            "canonical_name": ent["canonical_name"],
            "n_mentions": int(ent["n_mentions"]),
            "n_claims": len(roles),
            "identity": _identity_summary(eid, ent_identifiers),
            "attribute_timelines": timelines,
            "roles_per_claim": roles,
            "facts_vs_allegations": {"allegations": allegations},
            "linked_entities": linked,
            "evidence": evidence,
        }
        repo.upsert_dossier(eid, dossier)
        dossiers += 1

    repo.add_entity_attributes(attr_rows)
    return {"n_dossiers": dossiers, "n_attribute_rows": len(attr_rows)}


def _build_attributes(eid, grounded, texts, attr_rows_out):
    """Return (timelines, evidence_list, allegations)."""
    by_attr = defaultdict(list)
    allegations = []
    evidence = []
    for a in grounded:
        if a["predicate"] == "allegation":
            allegations.append(_evidence_item(a, texts))
            continue
        by_attr[a["predicate"]].append(a)
        evidence.append(_evidence_item(a, texts))

    timelines = {}
    for attr, alist in by_attr.items():
        # survivorship: group by value; tier + retraction handling
        tier_rank = CFG.SURVIVORSHIP_TIERS
        retracted_values = {a["object_value_norm"] for a in alist
                            if a["polarity"] in ("retracted", "negated")}
        value_rows = {}
        for a in alist:
            v = a["object_value_norm"] or a["object_value_raw"]
            tier = _tier(a)
            row = value_rows.get(v)
            if row is None or tier_rank[tier] > tier_rank[row["tier"]]:
                value_rows[v] = {
                    "value": a["object_value_raw"], "value_norm": v, "tier": tier,
                    "polarity": a["polarity"],
                    "valid_from": a.get("effective_from"), "valid_to": a.get("effective_to"),
                    "known_to": "retracted" if v in retracted_values else None,
                    "source": f"{a['source_doc_id']}[{a['source_span_start']}:{a['source_span_end']}]",
                    "assertion_id": a["assertion_id"],
                }
        surviving = [r for r in value_rows.values() if r["known_to"] != "retracted"]
        top_tier = max((tier_rank[r["tier"]] for r in surviving), default=0)
        top_vals = [r for r in surviving if tier_rank[r["tier"]] == top_tier]
        conflict = len({r["value_norm"] for r in top_vals}) > 1
        for r in value_rows.values():
            r["conflict_flag"] = 1 if (conflict and tier_rank[r["tier"]] == top_tier) else 0
            attr_rows_out.append({
                "attr_id": f"at_{uuid.uuid4().hex[:12]}", "entity_id": eid,
                "attribute": attr, "value_raw": r["value"], "value_norm": r["value_norm"],
                "valid_from": r["valid_from"], "valid_to": r["valid_to"],
                "known_from": None, "known_to": r["known_to"], "tier": r["tier"],
                "polarity": r["polarity"], "conflict_flag": r["conflict_flag"],
                "source_assertion_id": r["assertion_id"],
            })
        timelines[attr] = sorted(value_rows.values(),
                                 key=lambda r: (-CFG.SURVIVORSHIP_TIERS[r["tier"]], str(r["valid_from"])))
    return timelines, evidence, allegations


def _evidence_item(a, texts) -> dict:
    raw = texts.get(a["source_doc_id"], "")
    s, e = a["source_span_start"], a["source_span_end"]
    lo, hi = max(0, s - SNIPPET_PAD), min(len(raw), e + SNIPPET_PAD)
    return {
        "doc_id": a["source_doc_id"],
        "span": [int(s), int(e)],
        "snippet": raw[lo:hi],
        "highlight_offset": [int(s - lo), int(e - lo)],
        "machine_annotation": render_assertion_annotation(a),
    }


def _roles_per_claim(mids, mentions, docs) -> dict:
    roles = {}
    for mid in mids:
        if mid not in mentions.index:
            continue
        m = mentions.loc[mid]
        claim = docs.get(m["doc_id"], "UNKNOWN")
        role = CLASS_ROLE.get(m["entity_class"], m["entity_class"])
        roles.setdefault(claim, role)
    return roles


def _identity_summary(eid, ent_identifiers) -> dict:
    d = ent_identifiers.get(eid, {})
    return {
        "emails": sorted(d.get("has_email", [])),
        "phones": sorted(d.get("has_phone", [])),
        "npis": sorted(d.get("has_npi", [])),
        "tins": sorted(d.get("has_tin", [])),
        "email_domains": sorted(d.get("email_domain", [])),
        "addresses": sorted(d.get("addr", [])),
    }


def _linked_entities(eid, ent_identifiers, id_index, ent_to_mentions,
                     pair_by_mentions, entities) -> list:
    out = {}
    mine = ent_identifiers.get(eid, {})
    for field in ("has_email", "has_phone", "has_npi", "has_tin", "addr"):
        for v in mine.get(field, []):
            for other in id_index.get((field, v), set()):
                if other == eid:
                    continue
                shared_key = f"{field}={v}"
                # find a candidate pair between a mention of each (for annotation)
                pr = None
                for ma in ent_to_mentions[eid]:
                    for mb in ent_to_mentions[other]:
                        pr = pair_by_mentions.get(frozenset((ma, mb)))
                        if pr is not None:
                            break
                    if pr is not None:
                        break
                key = (other, field)
                if key not in out:
                    out[other] = out.get(other, {
                        "entity_id": other,
                        "entity_class": entities.loc[other]["entity_class"] if other in entities.index else "?",
                        "canonical_name": entities.loc[other]["canonical_name"] if other in entities.index else "?",
                        "shared": [], "degree": 1,
                    })
                    out[other]["annotation"] = render_link_annotation(shared_key, pr)
                if shared_key not in out[other]["shared"]:
                    out[other]["shared"].append(shared_key)
    # email-domain links (attorneys at same firm) as degree-2 context
    for dom in mine.get("email_domain", []):
        for other, od in ent_identifiers.items():
            if other != eid and dom in od.get("email_domain", []):
                if other not in out:
                    out[other] = {
                        "entity_id": other,
                        "entity_class": entities.loc[other]["entity_class"] if other in entities.index else "?",
                        "canonical_name": entities.loc[other]["canonical_name"] if other in entities.index else "?",
                        "shared": [f"email_domain={dom}"], "degree": 2,
                        "annotation": render_link_annotation(f"email_domain={dom}", None),
                    }
                elif f"email_domain={dom}" not in out[other]["shared"]:
                    out[other]["shared"].append(f"email_domain={dom}")
    return list(out.values())
