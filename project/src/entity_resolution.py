"""Layer 2: probabilistic entity resolution.

Replaces the hand-rolled pairwise scorer with Splink (Fellegi-Sunter record
linkage with EM-trained m/u probabilities), behind an `ERBackend` interface so a
managed engine (Senzing et al.) can be swapped in without touching Layers 3-4.

TWO ARCHITECTURAL CHANGES FROM THE PREVIOUS RESOLVER
----------------------------------------------------
1. **Calibrated probabilities.** Splink's EM training produces a real
   `match_probability` per pair rather than a hand-tuned weighted sum. That is
   the per-edge confidence the rest of the system needs.

2. **No destructive merge.** Output is a `same_as_edges` table; resolved
   identity is a THRESHOLD-DERIVED VIEW (connected components at a chosen
   threshold), materialized into `entity_snapshot`. Nothing is written down as
   "these are the same forever". A questionable link is a low-probability edge
   you filter at read time, not a structural mistake baked into the store.

   The previous design wrote merges permanently and enforced constraints as hard
   vetoes, which produced a failure mode where one mis-bound identifier
   permanently vetoed thousands of valid edges and split one person into ten
   entities. Under this model that cannot happen: constraints suppress edges
   before clustering, and the clustering itself is recomputable.
"""
from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict

import pandas as pd

from . import textnorm
from .repository import Repository
from .settings import CFG, Paths


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------
class ERBackend(ABC):
    """Pairwise entity resolution.

    Contract: `resolve(frame)` takes one row per mention (see build_mention_frame
    for the columns) and returns a DataFrame of candidate pairs with at least
    `mention_id_l`, `mention_id_r`, `match_probability`.

    To swap in a managed engine, implement this one method. Clustering,
    constraints, storage and every downstream layer are unchanged.
    """

    name = "abstract"

    @abstractmethod
    def resolve(self, frame: pd.DataFrame) -> pd.DataFrame: ...


# ---------------------------------------------------------------------------
# Mention feature frame
# ---------------------------------------------------------------------------
def build_mention_frame(repo: Repository) -> pd.DataFrame:
    """One row per mention with the comparison columns Splink needs.

    Identifier values come from identifier_observations (which includes orphans)
    joined back to whichever mention they bound to, plus the grounded assertions.
    """
    mentions = repo.table("mentions")
    docs = repo.table("documents").set_index("doc_id")
    claim_of = docs["claim_id"].to_dict()
    occ_of = docs["occurrence_id"].to_dict() if "occurrence_id" in docs.columns else {}

    ident: dict[str, dict[str, str]] = defaultdict(dict)
    try:
        obs = repo.table("identifier_observations")
        for _, o in obs.iterrows():
            mid = o["subject_mention_id"]
            if mid and o["value_norm"]:
                ident[mid].setdefault(o["kind"], o["value_norm"])
    except Exception:
        pass

    for _, a in repo.table("assertions").iterrows():
        if a["grounded"] != 1 or a["polarity"] in ("negated", "retracted"):
            continue
        k = {"has_email": "email", "has_phone": "phone", "has_npi": "npi",
             "has_tin": "tin", "has_ssn": "ssn", "has_dob": "dob",
             "has_address": "address"}.get(a["predicate"])
        if k:
            ident[a["subject_mention_id"]].setdefault(k, a["object_value_norm"] or "")

    rows = []
    for _, m in mentions.iterrows():
        mid = m["mention_id"]
        d = ident.get(mid, {})
        norm = m["norm_surface"] or textnorm.normalize_name(m["surface"])
        toks = norm.split()
        addr = d.get("address", "")
        rows.append({
            "mention_id": mid,
            "doc_id": m["doc_id"],
            "claim_id": claim_of.get(m["doc_id"], ""),
            "occurrence_id": occ_of.get(m["doc_id"], ""),
            "entity_class": m["entity_class"],
            "full_name": norm,
            # token-sorted name: the corpus deliberately plants order flips
            # ("Reyes, Alicia" vs "Alicia Reyes"), and a string-similarity
            # comparison scores those poorly. Sorting tokens normalizes the flip
            # so it becomes an exact match instead of a near-miss.
            "name_sorted": " ".join(sorted(toks)),
            "first_name": toks[0] if toks else "",
            "last_name": toks[-1] if toks else "",
            "name_soundex": textnorm.soundex(toks[-1]) if toks else "",
            "email": d.get("email", ""),
            "phone7": textnorm.phone_last7(d.get("phone", "")),
            "npi": d.get("npi", ""),
            "tin": d.get("tin", ""),
            "ssn": d.get("ssn", ""),
            "dob": d.get("dob", ""),
            "address_key": textnorm.address_key(addr),
            "inside_quoted": int(m["inside_quoted"]),
        })
    df = pd.DataFrame(rows)
    # CRITICAL: missing identifiers must be NULL, not "". Splink excludes NULLs
    # from blocking; an empty string is a VALUE, so every mention without an
    # address would block together into one ~20k-row block (~200M pairs) and
    # exhaust disk. Only the always-present name columns keep "" as a default.
    for col in ("email", "phone7", "npi", "tin", "ssn", "dob", "address_key"):
        df[col] = df[col].replace("", None)
    return df


# ---------------------------------------------------------------------------
# Splink backend
# ---------------------------------------------------------------------------
def comparison_specs():
    """(name, comparison, raw_value_columns) for every scored comparison.

    Single source of truth for the comparisons Splink scores: SplinkResolver
    builds its settings from this, and comparison_level_labels() (used by the
    QA viewer's match-lineage display) derives its gamma-level labels from the
    exact same objects, so the two can never drift apart.

    entity_class is deliberately absent: it is a noisy derived label from our
    own classifier, not identity evidence. Comparing it penalizes correct
    matches whenever the classifier disagreed with itself across two mentions
    of one entity.
    """
    import splink.comparison_library as cl

    return [
        ("first_name_last_name",
         cl.ForenameSurnameComparison("first_name", "last_name")
           .configure(term_frequency_adjustments=True),
         ["first_name", "last_name"]),
        ("name_sorted", cl.JaroWinklerAtThresholds("name_sorted", [0.95, 0.88]), ["name_sorted"]),
        ("email", cl.EmailComparison("email"), ["email"]),
        ("phone7", cl.ExactMatch("phone7"), ["phone7"]),
        ("npi", cl.ExactMatch("npi"), ["npi"]),
        ("address_key", cl.ExactMatch("address_key"), ["address_key"]),
        ("dob", cl.ExactMatch("dob"), ["dob"]),
    ]


def comparison_level_labels() -> dict:
    """{comparison_name: {gamma_level: human label}}, derived from the live
    comparison objects rather than hand-copied, so it can't drift from what
    Splink actually scored. gamma -1 always means both sides were null.

    Splink lists each comparison's levels most-specific-first after the null
    level; the stored gamma ("comparison vector value") counts up from 0 at
    the last (least specific, "All other comparisons") entry -- so reverse the
    non-null levels and enumerate.
    """
    out = {}
    for name, comp, _ in comparison_specs():
        levels = comp.get_comparison("duckdb").as_dict()["comparison_levels"]
        non_null = [lvl for lvl in levels if not lvl.get("is_null_level")]
        labels = {i: lvl.get("label_for_charts", "") for i, lvl in enumerate(reversed(non_null))}
        labels[-1] = "both sides null -- no evidence either way"
        out[name] = labels
    return out


class SplinkResolver(ERBackend):
    """Fellegi-Sunter linkage with EM-calibrated m/u probabilities."""

    name = "splink"

    def __init__(self, seed: int | None = None):
        self.seed = seed if seed is not None else CFG.SEED

    def _settings(self):
        from splink import SettingsCreator, block_on

        return SettingsCreator(
            link_type="dedupe_only",
            unique_id_column_name="mention_id",
            # Blocking: each rule proposes candidates independently; their union
            # is what Splink scores. Mirrors the previous multi-pass design.
            blocking_rules_to_generate_predictions=[
                block_on("email"),
                block_on("npi"),
                block_on("tin"),
                block_on("phone7"),
                block_on("address_key"),
                block_on("full_name"),
                block_on("name_sorted"),
                block_on("name_soundex", "first_name"),
                block_on("last_name"),
            ],
            comparisons=[c for _, c, _ in comparison_specs()],
            retain_intermediate_calculation_columns=True,
        )

    def resolve(self, frame: pd.DataFrame) -> pd.DataFrame:
        from splink import DuckDBAPI, Linker, block_on

        linker = Linker(frame, self._settings(), db_api=DuckDBAPI())

        # Prior: the chance two randomly drawn mentions co-refer. Splink defaults
        # to 1e-4, which is badly wrong for this corpus (entities recur heavily),
        # and the prior shifts every posterior. Estimate it from high-precision
        # deterministic rules instead of accepting the default.
        try:
            linker.training.estimate_probability_two_random_records_match(
                [block_on("email"), block_on("npi"),
                 "l.full_name = r.full_name and l.dob = r.dob"],
                recall=CFG.ER_DETERMINISTIC_RECALL,
            )
        except Exception:
            pass

        linker.training.estimate_u_using_random_sampling(max_pairs=2_000_000, seed=self.seed)

        # EM: each training block holds one field fixed, so the OTHER comparisons
        # get trained. Blocking on full_name cannot train the name comparison, so
        # identifier-led blocks are included to cover name, and name-led blocks to
        # cover email/identifiers.
        for rule in (block_on("full_name"),
                     block_on("phone7"),
                     block_on("address_key"),
                     block_on("last_name", "first_name"),
                     block_on("npi")):
            try:
                linker.training.estimate_parameters_using_expectation_maximisation(rule)
            except Exception:
                continue   # a block too sparse to train on is skipped, not fatal
        preds = linker.inference.predict(threshold_match_probability=0.01)
        df = preds.as_pandas_dataframe()
        keep = ["mention_id_l", "mention_id_r", "match_probability", "match_weight"]

        # Persist the trained model (settings + m/u parameters) so the QA
        # viewer can later re-score any specific pair on demand via
        # linker.inference.compare_two_records() -- real Splink output,
        # computed lazily per click instead of serialized for every one of
        # the (possibly millions of) scored edges up front.
        try:
            linker.misc.save_model_to_json(str(Paths.store / "splink_model.json"), overwrite=True)
        except Exception:
            pass

        return df[[c for c in keep if c in df.columns]]


def get_backend(name: str | None = None) -> ERBackend:
    return SplinkResolver()


# ---------------------------------------------------------------------------
# Constraints -- suppression, not permanent veto
# ---------------------------------------------------------------------------
def _val(d: dict, key: str):
    """Return a real value or None.

    Missing identifiers arrive as NaN from pandas, and NaN is TRUTHY while
    NaN != NaN is True -- so a naive `if va and vb and va != vb` marks every
    pair of mentions with NO identifier as *conflicting*. That suppressed all
    2.49M edges in an earlier run and left every mention as its own entity.
    """
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, float):      # NaN
        return None
    v = str(v).strip()
    return v or None


def cannot_link_reason(a: dict, b: dict) -> str | None:
    """Structural reasons two mentions cannot be the same entity.

    Applied by suppressing the edge before clustering. Conflicts require BOTH
    sides to actually carry a value; a missing identifier is not evidence of
    anything. Identifier conflicts are otherwise deliberately narrow -- a single
    mis-bound identifier should lower a pair's probability, not permanently
    partition an entity.
    """
    persons = {"claimant", "attorney", "adjuster"}
    ca, cb = _val(a, "entity_class"), _val(b, "entity_class")
    if (ca in persons and cb == "repair_shop") or (cb in persons and ca == "repair_shop"):
        return "person_vs_org"
    sa = textnorm.name_suffix(_val(a, "full_name") or "")
    sb = textnorm.name_suffix(_val(b, "full_name") or "")
    ak, bk = _val(a, "address_key"), _val(b, "address_key")
    if sa and sb and sa != sb and ak and ak == bk:
        return "jr_sr_conflict"
    for fld in ("npi", "tin", "ssn"):
        va, vb = _val(a, fld), _val(b, fld)
        if va is not None and vb is not None and va != vb:
            return f"conflicting_{fld}"
    return None


# ---------------------------------------------------------------------------
# Threshold-derived identity
# ---------------------------------------------------------------------------
def cluster_at(edges: pd.DataFrame, mention_ids: list[str], threshold: float) -> dict:
    """Connected components over edges at or above `threshold`.

    This is a VIEW: changing the threshold re-partitions without rewriting any
    stored edge. Returns {mention_id: entity_id}.
    """
    parent = {m: m for m in mention_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    sel = edges[edges["match_probability"] >= threshold]
    # .itertuples()/.to_numpy() rather than .iterrows(): this runs on every
    # threshold change (interactively, from the QA viewer) as well as once
    # per point in threshold_sweep, and .iterrows() boxing each row into a
    # Series made that visibly slow at corpus scale.
    for a, b in zip(sel["mention_id_l"].to_numpy(), sel["mention_id_r"].to_numpy()):
        if a in parent and b in parent:
            union(a, b)

    groups = defaultdict(list)
    for m in mention_ids:
        groups[find(m)].append(m)
    out = {}
    for root, members in groups.items():
        eid = f"E{uuid.uuid5(uuid.NAMESPACE_OID, str(sorted(members))).hex[:12]}"
        for m in members:
            out[m] = eid
    return out


def threshold_sweep(edges: pd.DataFrame, mention_ids: list[str],
                    thresholds=(0.5, 0.7, 0.8, 0.9, 0.95, 0.99)) -> list[dict]:
    """Entity count at each threshold -- the operating curve, not one number."""
    out = []
    for t in thresholds:
        lab = cluster_at(edges, mention_ids, t)
        out.append({"threshold": t, "n_entities": len(set(lab.values()))})
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(repo: Repository, threshold: float | None = None,
        backend: ERBackend | None = None) -> dict:
    threshold = CFG.ER_LINK_THRESHOLD if threshold is None else threshold
    backend = backend or get_backend()

    frame = build_mention_frame(repo)
    if frame.empty:
        return {"error": "no mentions"}

    edges = backend.resolve(frame)

    # suppress structurally impossible pairs
    feat = frame.set_index("mention_id").to_dict("index")
    reasons = []
    keep_mask = []
    for _, e in edges.iterrows():
        a, b = feat.get(e["mention_id_l"]), feat.get(e["mention_id_r"])
        r = cannot_link_reason(a, b) if (a and b) else None
        reasons.append(r)
        keep_mask.append(r is None)
    edges = edges.assign(suppressed_reason=reasons)
    live = edges[keep_mask]

    # persist every scored edge (suppressed ones too, for auditability)
    repo.conn.execute("PRAGMA foreign_keys=OFF")
    for t in ("same_as_edges", "entity_snapshot", "entity_members",
              "entity_versions", "entity_attributes", "dossiers", "entities"):
        repo.conn.execute(f"DELETE FROM {t}")
    repo.conn.commit()
    repo.conn.execute("PRAGMA foreign_keys=ON")

    repo.add_same_as_edges([
        {"mention_id_a": r["mention_id_l"], "mention_id_b": r["mention_id_r"],
         "probability": float(r["match_probability"]),
         "match_weight": float(r.get("match_weight", 0.0) or 0.0),
         "backend": backend.name,
         "suppressed_reason": r["suppressed_reason"]}
        for _, r in edges.iterrows()
    ])

    mention_ids = frame["mention_id"].tolist()
    labels = cluster_at(live, mention_ids, threshold)
    sweep = threshold_sweep(live, mention_ids)

    # materialize the view at the operating threshold
    ent_rows, mem_rows, snap_rows = [], [], []
    by_entity = defaultdict(list)
    for mid, eid in labels.items():
        by_entity[eid].append(mid)
    cls_of = frame.set_index("mention_id")["entity_class"].to_dict()
    name_of = repo.table("mentions").set_index("mention_id")["surface"].to_dict()
    for eid, members in by_entity.items():
        from collections import Counter
        cname = Counter(name_of.get(m, "") for m in members).most_common(1)[0][0]
        kls = Counter(cls_of.get(m, "claimant") for m in members).most_common(1)[0][0]
        ent_rows.append({"entity_id": eid, "entity_class": kls,
                         "canonical_name": cname, "version_id": f"{eid}.t{threshold}",
                         "n_mentions": len(members)})
        for m in members:
            mem_rows.append({"entity_id": eid, "mention_id": m,
                             "version_id": f"{eid}.t{threshold}"})
            snap_rows.append({"entity_id": eid, "mention_id": m,
                              "threshold": threshold})
    repo.add_entities(ent_rows)
    repo.add_entity_members(mem_rows)
    repo.add_entity_snapshot(snap_rows)

    return {
        "backend": backend.name,
        "n_mentions": len(mention_ids),
        "n_edges_scored": len(edges),
        "n_edges_suppressed": int(len(edges) - len(live)),
        "suppression_reasons": dict(pd.Series(
            [r for r in reasons if r]).value_counts()) if any(reasons) else {},
        "operating_threshold": threshold,
        "n_entities": len(by_entity),
        "threshold_sweep": sweep,
    }
