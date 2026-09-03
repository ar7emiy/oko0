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
import math
import uuid
from abc import ABC, abstractmethod
from collections import Counter, defaultdict

import pandas as pd

from . import blocking, runlog, textnorm
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
             "has_vin": "vin", "has_address": "address"}.get(a["predicate"])
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
            "vin": d.get("vin", ""),
            "dob": d.get("dob", ""),
            # Kept as the coarse BLOCKING key. Scoring uses the components
            # below, because ExactMatch on this composite gives an address
            # pair with a missing zip no evidence at all rather than less.
            "address_key": textnorm.address_key(addr),
            **{f"address_{k}": v for k, v in textnorm.address_parts(addr).items()},
            "inside_quoted": int(m["inside_quoted"]),
        })
    df = pd.DataFrame(rows)
    # CRITICAL: missing identifiers must be NULL, not "". Splink excludes NULLs
    # from blocking; an empty string is a VALUE, so every mention without an
    # address would block together into one ~20k-row block (~200M pairs) and
    # exhaust disk. Only the always-present name columns keep "" as a default.
    #
    # The address components matter here too, and more subtly: an empty
    # address_state would otherwise make every address-less mention agree with
    # every other on "state", which reads as evidence rather than absence.
    for col in ("email", "phone7", "npi", "tin", "ssn", "vin", "dob",
                "address_key", "address_street", "address_city",
                "address_state", "address_zip"):
        df[col] = df[col].replace("", None)
    return df


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------
# ORDER IS LOAD-BEARING. Splink stamps every predicted pair with `match_key`,
# the index of the blocking rule that generated it, so this list is what makes
# the embedding lane's contribution measurable instead of asserted: a pair with
# match_key == the index of "emb_bucket" is one NO deterministic rule proposed.
# Appending only at the end keeps historical match_keys comparable across runs.
BLOCKING_RULES = [
    ("email",),
    ("npi",),
    ("tin",),
    ("phone7",),
    ("address_key",),
    ("full_name",),
    ("name_sorted",),
    ("name_soundex", "first_name"),
    ("last_name",),
    ("emb_bucket",),          # the embedding recall net -- see src/blocking.py
    # Appended, never inserted: match_key is the rule's INDEX, so inserting
    # would silently renumber every historical edge's provenance.
    ("ssn",),
    ("vin",),
]
BLOCKING_RULE_NAMES = ["+".join(r) for r in BLOCKING_RULES]
EMB_RULE_INDEX = BLOCKING_RULE_NAMES.index("emb_bucket")


def _rule_name(match_key) -> str | None:
    """Splink's match_key (rule index) -> the rule's readable name."""
    if match_key is None or (isinstance(match_key, float) and pd.isna(match_key)):
        return None
    k = int(match_key)
    return BLOCKING_RULE_NAMES[k] if 0 <= k < len(BLOCKING_RULE_NAMES) else f"rule_{k}"


MODEL_PATH = Paths.store / "splink_model.json"
SIGNATURE_PATH = Paths.store / "splink_model.signature.json"


class ModelOutOfDate(RuntimeError):
    """The frozen model was trained with a different comparison/blocking set."""


def model_signature(frame: pd.DataFrame | None = None,
                    drop: set | None = None) -> dict:
    """What the frozen model must agree with to be safely reusable.

    The ingest path scores arriving notes with the model saved at backfill
    (`MODEL_PATH`) so that every edge in the store is calibrated identically.
    That is correct only while the saved model's comparison set still matches
    the code's. Change `comparison_specs` -- as adding tin/ssn/vin and the
    graded address comparison just did -- and the saved model keeps scoring new
    notes with the OLD evidence model, indefinitely and silently, producing a
    store whose edges were scored two different ways with nothing to say which.

    This is the same failure class as artifacts at different data versions; the
    remedy is the same one used there: make the mismatch loud.
    """
    return {
        # DECLARED is what the code offers, independent of any corpus. This
        # is the only part check_model_current compares, because it is the
        # only part that changes when a developer edits the evidence model.
        "declared": [n for n, _, _ in comparison_specs()],
        # TRAINED is what survived pruning on this corpus. Recorded for the
        # reader, NOT compared: it is data-dependent, so a client whose
        # notes carry no SSNs legitimately trains a smaller set than one
        # whose notes do, and neither is a stale model.
        "trained": [n for n, _, _ in comparison_specs(frame, drop=drop)],
        "blocking_rules": list(BLOCKING_RULE_NAMES),
    }


def check_model_current(frame: pd.DataFrame | None = None) -> dict:
    """Raise if the frozen model predates the current comparison set."""
    want = model_signature(frame)
    if not SIGNATURE_PATH.exists():
        raise ModelOutOfDate(
            f"{MODEL_PATH.name} has no signature file, so it predates model "
            "versioning and cannot be shown to match the current comparison "
            "set. Re-run the backfill (ingest.backfill) to retrain."
        )
    have = json.loads(SIGNATURE_PATH.read_text(encoding="utf-8"))
    # Compare the DECLARED set and the blocking rules only. The trained set is
    # data-dependent -- a corpus with no SSNs legitimately trains a smaller set
    # than one with them (see _prune_absent) -- so comparing it would report
    # every ordinary corpus difference as a stale model.
    drift = {k: (have.get(k), want[k]) for k in ("declared", "blocking_rules")
             if have.get(k) != want[k]}
    if drift:
        added = sorted(set(want["declared"]) - set(have.get("declared", [])))
        removed = sorted(set(have.get("declared", [])) - set(want["declared"]))
        raise ModelOutOfDate(
            "The frozen Splink model was trained against a different evidence "
            f"model: comparisons added {added or 'none'}, removed "
            f"{removed or 'none'}; blocking {have.get('blocking_rules')} -> "
            f"{want['blocking_rules']}. Scoring arriving notes with it would put "
            "edges calibrated two different ways in one store. Re-run the "
            "backfill to retrain."
        )
    return have


# ---------------------------------------------------------------------------
# Calibration: the match prior, and which parameters are real
# ---------------------------------------------------------------------------
def lambda_rules():
    """High-precision rules used to estimate the match prior (lambda).

    Lambda -- `probability_two_random_records_match`, the chance two randomly
    drawn mentions co-refer -- is a PRIOR, applied to every posterior. Splink
    estimates it by counting the pairs these deterministic rules catch and
    dividing by an assumed recall (CFG.ER_DETERMINISTIC_RECALL).

    WHY THESE RULES AND NOT THE OBVIOUS ONES
    ----------------------------------------
    The first version of this list was [email, npi, full_name AND dob] -- the
    textbook choice, because those are the fields you trust. Measured on this
    corpus, they are also the fields that are almost always ABSENT: email is
    non-null on 55 of 922 mentions and npi on 7. The rules barely fired, so:

        lambda estimated  0.000764        lambda in truth  0.012097

    a 16x underestimate, which is ~4 bits subtracted from every single edge.
    Nothing compensates for a wrong prior -- EM re-fits m against whatever u it
    is given, so u errors partly wash out, but lambda is applied at the end and
    simply shifts the whole distribution. Measured end-to-end against ground
    truth, at the shipped operating threshold of 0.45:

        shipped rules   B-cubed F1 0.604   recall 0.438    515 entities
        rules below     B-cubed F1 0.800   recall 0.728     81 entities

    (42 entities is the truth for this 60-document subset, so the corpus went
    from ~12x over-split to ~1.9x; the residue is the u bias, TODO T0.5.) The
    curve also goes from cliff-edged to flat:
    worst F1 anywhere in 0.20-0.95 rises from 0.185 to 0.783, which is what
    makes a shipped threshold survive contact with a client's data.

    So the selection principle is NOT "which fields are most trustworthy" but
    "which high-precision rules actually FIRE on the data in hand". A name plus
    one corroborating field is the shape that survives sparse identifiers.

    Rejected: Splink's
    `populate_probability_two_random_records_match_from_trained_values`, which
    derives lambda from the trained model instead. Measured, it returns 0.619 --
    it claims 62% of all random mention pairs co-refer. It scores acceptably at
    0.45 by accident and peaks at 0.99, i.e. it destroys the meaning of the
    threshold. A prior nobody can defend out loud is not a calibration.

    WHAT A CLIENT MAY HAVE TO TUNE
    ------------------------------
    The last rule is claim-scoped, and its precision depends on how granular the
    client's `claim_id` is. On many small claims it is very precise. On a corpus
    that is one enormous claim it degenerates to "same sorted name" and will
    over-fire, biasing lambda UP. It is already ~2x high here (0.0264 estimated
    against 0.0121 measured) and the end-to-end result sits at the ceiling a
    perfect lambda reaches, so 2x high is tolerable where 16x low was not --
    the posterior is far more sensitive to underestimating the prior.

    The check is in the run output rather than in a comment: `calibration`
    reports lambda every run, alongside what each agreeing field is worth in
    bits. If a client's lambda implies more co-reference than their corpus
    plausibly contains, it is visible without a labelled set.
    """
    from splink import block_on
    return [
        block_on("email"),
        block_on("npi"),
        block_on("phone7"),
        "l.full_name = r.full_name and l.dob = r.dob",
        "l.full_name = r.full_name and l.address_key = r.address_key",
        # Within ONE claim, two mentions with the same token-sorted name are the
        # same party in all but pathological cases. This is the rule that makes
        # the estimate fire at all on identifier-sparse data.
        "l.name_sorted = r.name_sorted and l.claim_id = r.claim_id",
    ]


class ModelNotFullyTrained(RuntimeError):
    """EM could not estimate every m/u parameter and Splink invented defaults."""


def training_completeness(linker) -> dict:
    """Which m/u parameters EM never estimated, and what stood in for them.

    Splink logs "Your model is not yet fully trained ... will use default
    values" and carries on. The substituted value is not a neutral placeholder:
    for a two-level comparison the invented m for the agreement level is 0.95
    regardless of the field, so an exact NPI match -- a nationally unique
    identifier -- was contributing +2.73 bits, LESS than an exact name match at
    +4.96. Uncalibrated evidence reported as calibrated probability is precisely
    the failure this system's headline claim cannot survive, so the untrained
    set is returned as data rather than left in a log line.

    TWO kinds of substitution are reported, because Splink distinguishes them
    and they mean different things:

    * `never_estimated` -- the parameter is None; EM never reached this level at
      all, and Splink substitutes a level-count-derived default (0.95 for the
      agreement level of a two-level comparison, whatever the field is).
    * `not_observed_in_training` -- EM ran but saw zero pairs at this level, and
      Splink substitutes 1e-6. That is a near-veto rather than a guess, so
      missing it would understate the damage rather than overstate it.

    Returns {"fully_trained": bool, "untrained": [...], "by_comparison": {...}}
    where each untrained entry names the comparison, the level, which of m/u was
    missing, and the value Splink substituted.
    """
    from splink.internals.comparison import _default_m_values, _default_u_values
    from splink.internals.constants import LEVEL_NOT_OBSERVED_TEXT

    untrained, by_comp = [], defaultdict(list)
    for comp in linker._settings_obj.comparisons:
        levels = [lv for lv in comp.comparison_levels if not lv.is_null_level]
        n = len(levels)
        dm, du = _default_m_values(n), _default_u_values(n)
        for lv in levels:
            cvv = lv.comparison_vector_value
            for which, raw, default in (("m", lv._m_probability, dm[cvv]),
                                        ("u", lv._u_probability, du[cvv])):
                if raw is None:
                    reason, value = "never_estimated", float(default)
                elif raw == LEVEL_NOT_OBSERVED_TEXT:
                    reason, value = "not_observed_in_training", 1e-6
                else:
                    continue
                untrained.append({"comparison": comp.output_column_name,
                                  "level": lv.label_for_charts,
                                  "comparison_vector_value": cvv,
                                  "parameter": which,
                                  "reason": reason,
                                  "substituted_default": round(value, 8)})
                by_comp[comp.output_column_name].append(cvv)
    # Comparisons whose AGREEMENT level -- the highest comparison_vector_value,
    # the one that fires when the two sides match -- carries an invented
    # parameter. Only that level matters for this purpose: email has an
    # untrained Jaro-Winkler-on-username level and is still one of the better
    # signals, but a comparison whose top level is invented contributes pure
    # fiction whenever it agrees, and Splink's two-level default renders that
    # fiction as +10 bits.
    untrainable = set()
    for comp in linker._settings_obj.comparisons:
        levels = [lv for lv in comp.comparison_levels if not lv.is_null_level]
        if not levels:
            continue
        top = max(lv.comparison_vector_value for lv in levels)
        if any(r["comparison"] == comp.output_column_name
               and r["comparison_vector_value"] == top for r in untrained):
            untrainable.add(comp.output_column_name)

    return {"fully_trained": not untrained,
            "n_untrained_parameters": len(untrained),
            "untrained": untrained,
            "untrainable_agreement": sorted(untrainable),
            # {comparison: {gamma levels affected}} -- used to flag the edges
            # that actually landed on a substituted level.
            "by_comparison": {k: sorted(set(v)) for k, v in by_comp.items()}}


def calibration_report(linker) -> dict:
    """Everything about this model that a reader has to trust, in one dict.

    The prior, the per-comparison evidence in bits, and the untrained set. It
    goes into the run output because the alternative -- a number in a config
    comment -- was measured to have drifted out of true without anything
    noticing (see CFG.ER_LINK_THRESHOLD).
    """
    s = linker._settings_obj
    weights = {}
    for comp in s.comparisons:
        levels = [lv for lv in comp.comparison_levels if not lv.is_null_level]
        top = max(levels, key=lambda lv: lv.comparison_vector_value)
        try:
            m, u = top.m_probability, top.u_probability
        except Exception:
            continue
        if m and u:
            weights[comp.output_column_name] = {
                "level": top.label_for_charts,
                "m": round(float(m), 6), "u": round(float(u), 6),
                "match_weight_bits": round(math.log2(m / u), 3),
            }
    comp_ness = training_completeness(linker)
    return {
        "probability_two_random_records_match":
            round(float(s._probability_two_random_records_match), 8),
        "lambda_estimator": "deterministic_rules",
        "n_lambda_rules": len(lambda_rules()),
        "agreement_weights_bits": weights,
        **comp_ness,
    }


def lane_provenance(edges: pd.DataFrame) -> dict:
    """How many scored pairs each blocking rule was responsible for.

    `match_key` is the index of the rule that produced the pair; Splink assigns
    the FIRST rule that fires, so a pair credited to emb_bucket is one that no
    deterministic rule proposed at all. That count is the recall the embedding
    lane bought, and it is the number to look at when deciding whether the lane
    is earning its cost.
    """
    if "match_key" not in edges.columns:
        return {}
    keys = pd.to_numeric(edges["match_key"], errors="coerce").dropna().astype(int)
    return {_rule_name(k): int(v) for k, v in sorted(keys.value_counts().items())}


# ---------------------------------------------------------------------------
# Splink backend
# ---------------------------------------------------------------------------
def comparison_specs(frame: pd.DataFrame | None = None, drop: set | None = None):
    """(name, comparison, raw_value_columns) for every scored comparison.

    Pass `frame` to drop comparisons whose columns are entirely absent from the
    data in hand. See `_prune_absent` for why that is a correctness measure and
    not an optimisation.

    Single source of truth for the comparisons Splink scores: SplinkResolver
    builds its settings from this, and comparison_level_labels() (used by the
    QA viewer's match-lineage display) derives its gamma-level labels from the
    exact same objects, so the two can never drift apart.

    entity_class is deliberately absent: it is a noisy derived label from our
    own classifier, not identity evidence. Comparing it penalizes correct
    matches whenever the classifier disagreed with itself across two mentions
    of one entity.

    TIN, SSN AND VIN WERE MISSING, AND THAT WAS NOT A DECISION
    ----------------------------------------------------------
    Until 2026-09-02 this list held name, email, phone, npi, address and dob.
    Measured against the ground-truth manifest, that left **305 of 1,622
    planted identifiers (19%) contributing no evidence at all**:

        ssn  125   in the frame, never blocked, never compared -- it could only
                   VETO a merge via cannot_link_reason, never support one
        vin  140   no detector anywhere; `vin` was a declared identifier kind
                   in the schema with nothing to produce it
        tin   40   blocked, so it proposed candidates, then contributed zero
                   evidence to the score of the pairs it proposed

    Meanwhile NPI -- the rarest identifier in the corpus at 74 -- was compared.
    Nothing flagged this because until T0.4 no run reported what each field was
    worth, so a field missing from the model was indistinguishable from a field
    the model found uninformative.
    """
    import splink.comparison_library as cl

    return _prune_absent([
        ("first_name_last_name",
         cl.ForenameSurnameComparison("first_name", "last_name")
           .configure(term_frequency_adjustments=True),
         ["first_name", "last_name"]),
        ("name_sorted", name_sorted_comparison(), ["name_sorted"]),
        ("email", cl.EmailComparison("email"), ["email"]),
        ("phone7", cl.ExactMatch("phone7"), ["phone7"]),
        ("npi", cl.ExactMatch("npi"), ["npi"]),
        ("tin", cl.ExactMatch("tin"), ["tin"]),
        ("ssn", cl.ExactMatch("ssn"), ["ssn"]),
        ("vin", cl.ExactMatch("vin"), ["vin"]),
        ("address", address_comparison(),
         ["address_street", "address_city", "address_state", "address_zip"]),
        ("dob", cl.ExactMatch("dob"), ["dob"]),
    ], frame, drop)


def _prune_absent(specs: list, frame: pd.DataFrame | None,
                  drop: set | None = None) -> list:
    """Drop comparisons this corpus cannot support.

    A comparison Splink cannot train is not neutral. It substitutes a default,
    and for a two-level comparison that default is m=0.95 / u=0.0009 -- which
    renders as **+10 bits, the strongest signal in the model**, entirely
    invented. The "else" default is worse: u=1.6, which is not a probability at
    all, and prices disagreement at -5 bits.

    Two filters, and the second exists because the first was measured to be
    insufficient:

    1. **Absent** -- the column holds no value anywhere. First seen when ssn and
       vin were added while the corpus contained none of either (D21).

    2. **Present but untrainable** -- `drop`, supplied by the caller after a
       first training pass. PRESENCE IS NOT TRAINABILITY. Once the corpus DID
       carry SSNs, the columns stopped being empty, survived filter 1, and were
       still untrainable: ~13 of 1013 mentions carry an SSN, so almost no
       blocked pair has one on both sides and EM never observes the levels. The
       fabricated +10 bits came straight back, and B-cubed F1 fell from 0.861 to
       0.812. The falsification test written for T0.7 falsified T0.7.

    Keeping the comparisons DECLARED and pruning them per-corpus is what makes
    this a tunable object: a client whose notes carry enough SSNs to train on
    gets the comparison; one whose notes do not is never shown an invented
    weight for it. Neither client edits code.
    """
    if frame is None and not drop:
        return specs
    drop = drop or set()
    kept = []
    for name, comp, cols in specs:
        if name in drop:
            continue
        if frame is not None:
            present = [c for c in cols if c in frame.columns]
            if present and not any(frame[c].notna().any() for c in present):
                continue
        kept.append((name, comp, cols))
    return kept




def name_sorted_comparison():
    """Jaro-Winkler on the token-sorted name, plus a CONTAINMENT level.

    WHY CONTAINMENT. `name_sorted` is the space-joined sorted tokens, so a bare
    surname is a token subset of the full name: "wilson" inside "marge wilson".
    String similarity cannot see that -- measured, `token_set_jw("wilson",
    "marge wilson")` is **0.500**, far below the 0.88 level -- so the resolver
    had no way to link a partial name to its full form at all.

    That did not matter while the extractor was throwing bare surnames away.
    Fixing D30 admitted them (entity recall 0.883 -> 0.971) and immediately
    exposed the gap: 60 of 735 mentions are now a single token, and B-cubed F1
    fell 0.920 -> 0.875 because those mentions floated free into entities of
    their own. **Better extraction made resolution look worse, because the
    comparison model had never been asked to handle what it now receives.**

    The level is deliberately below the fuzzy ones. Containment is real
    evidence but weaker than a near-exact match: "wilson" is contained in both
    "marge wilson" and "grace wilson", so it should raise a candidate's
    probability, not settle it. EM prices exactly how much it is worth.

    Padding with spaces makes the test token-wise rather than substring-wise --
    without it, "son" would match "wilson".
    """
    import splink.comparison_level_library as cll
    from splink.internals.comparison_library import CustomComparison

    L, R = '"name_sorted_l"', '"name_sorted_r"'
    contained = (f"(' ' || {L} || ' ') LIKE ('%' || ' ' || {R} || ' ' || '%') "
                 f"OR (' ' || {R} || ' ') LIKE ('%' || ' ' || {L} || ' ' || '%')")

    return CustomComparison(
        output_column_name="name_sorted",
        comparison_description="token-sorted name: exact, fuzzy, or contained",
        comparison_levels=[
            cll.NullLevel("name_sorted"),
            cll.ExactMatchLevel("name_sorted"),
            cll.JaroWinklerLevel("name_sorted", 0.95),
            cll.JaroWinklerLevel("name_sorted", 0.88),
            # Containment SPLIT BY CORROBORATION, because measured on its own it
            # over-merges: "wilson" is contained in both "marge wilson" and
            # "grace wilson", and a single containment level took B-cubed
            # precision at 0.45 from 0.777 to 0.684 while fixing the entity
            # count (58 -> 41 against 42 gold). Both halves of that were real.
            #
            # Within one claim a bare surname is almost always the party the
            # note already introduced. Across claims it is a coincidence of
            # surname far more often. Two levels let EM price them separately
            # instead of averaging a strong signal and a weak one into one
            # number that serves neither.
            cll.CustomLevel(
                f'({contained}) AND "claim_id_l" = "claim_id_r"',
                label_for_charts="name contained in the other, same claim",
            ),
            cll.CustomLevel(
                contained,
                label_for_charts="name contained in the other, different claim",
            ),
            cll.ElseLevel(),
        ],
    )


def address_comparison():
    """One graded address comparison, not four independent ones.

    WHY GRADED. The previous model compared `address_key` -- a single opaque
    composite of number|street|zip -- with ExactMatch, so agreement was
    all-or-nothing:

        "1420 Maple Street, Springfield, IL 62704"   ->  1420|maple|62704
        "1420 Maple Street, Springfield, IL"         ->  1420|maple

    Two writings of one address, and the second pair earns not weaker evidence
    but *none*. Conversely "Springfield, IL 62704" collapses to
    "springfield|62704" and exact-matches every other address in that zip, so
    the same mechanism carried a false-negative and a false-positive risk at
    once.

    WHY ONE COMPARISON AND NOT FOUR. Street, city, state and zip are heavily
    correlated -- agreeing on a street almost guarantees agreeing on the city.
    Fellegi-Sunter assumes comparisons are conditionally independent given match
    status, so four separate comparisons would count one piece of evidence four
    times and inflate the weight on exactly the pairs that need care. Ordered,
    mutually exclusive levels inside a single comparison price the combination
    once.

    Four non-null levels, not eight: every level EM cannot reach becomes a
    Splink-invented default (see training_completeness), and address components
    are sparse enough that a finer ladder would buy resolution nobody trained.

    NULL semantics are load-bearing. build_mention_frame nulls empty components,
    and in SQL `NULL = NULL` is not true -- so a missing component never
    silently agrees with another missing one.

    SQL DIALECT NOTE. Level SQL must use the "<col>_l" / "<col>_r" suffixed
    form, not "l.<col>" / "r.<col>". Both work during predict(), but the m/u
    re-estimation step runs the same SQL against a single already-joined table
    where no `l`/`r` aliases exist -- and the failure surfaces only there, deep
    in a generated UNION ALL, as `Binder Error: Referenced table "l" not found`.
    Splink's own levels avoid this by rendering through ColumnExpression.name_l.
    """
    import splink.comparison_level_library as cll
    from splink.internals.comparison_library import CustomComparison

    def both(c):
        return f'"address_{c}_l" = "address_{c}_r"'

    def missing(side):
        return (f'("address_street_{side}" IS NULL AND '
                f'"address_city_{side}" IS NULL AND '
                f'"address_zip_{side}" IS NULL)')

    return CustomComparison(
        output_column_name="address",
        comparison_description="address, graded by which components agree",
        comparison_levels=[
            cll.CustomLevel(
                f"{missing('l')} OR {missing('r')}",
                label_for_charts="one side has no address at all",
            ).configure(is_null_level=True),
            cll.CustomLevel(
                f'{both("street")} AND ({both("zip")} OR {both("city")})',
                label_for_charts="same street, corroborated by zip or city",
            ),
            cll.CustomLevel(
                both("street"),
                label_for_charts="same street only",
            ),
            cll.CustomLevel(
                f'{both("zip")} OR ({both("city")} AND {both("state")})',
                label_for_charts="same locality (zip, or city+state)",
            ),
            cll.ElseLevel(),
        ],
    )


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
        # Splink's null level is an OR ("<col>_l IS NULL OR <col>_r IS NULL"),
        # not an AND -- one side can carry a real value while the other is
        # missing and this level still applies. Don't claim "both".
        labels[-1] = "one or both sides missing -- no evidence either way"
        out[name] = labels
    return out


class SplinkResolver(ERBackend):
    """Fellegi-Sunter linkage with EM-calibrated m/u probabilities."""

    name = "splink"

    def __init__(self, seed: int | None = None):
        self.seed = seed if seed is not None else CFG.SEED
        # Populated by resolve(); read by run() for the run output.
        self.calibration: dict = {}

    def _settings(self, frame: pd.DataFrame | None = None, drop: set | None = None):
        from splink import SettingsCreator, block_on

        return SettingsCreator(
            link_type="dedupe_only",
            unique_id_column_name="mention_id",
            # Blocking: each rule proposes candidates independently; their
            # union is what Splink scores. Nine deterministic key rules plus
            # the embedding recall net (src/blocking.py), which proposes the
            # pairs that share no key at all.
            blocking_rules_to_generate_predictions=[
                block_on(*rule) for rule in BLOCKING_RULES
            ],
            # `frame` prunes comparisons over columns this corpus has no
            # values for at all -- see _prune_absent. Without it Splink
            # invents their parameters and reports the result as evidence.
            comparisons=[c for _, c, _ in comparison_specs(frame, drop=drop)],
            retain_intermediate_calculation_columns=True,
        )

    def resolve(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Train, and if a comparison turns out to be untrainable, train again
        without it.

        The second pass is not defensive tidiness -- it is measured. A
        comparison Splink cannot train gets a substituted default, and for a
        two-level comparison that default renders as +10 bits: the strongest
        signal in the model, invented. Dropping the column when it is EMPTY is
        not enough, because presence is not trainability: with SSNs on ~13 of
        1013 mentions the column is non-empty, survives the emptiness filter,
        and still has no blocked pair carrying one on both sides. Measured, that
        cost B-cubed F1 0.861 -> 0.812.

        So the trainability test is the training itself. One extra pass, seconds
        at this scale, and it is exact rather than a coverage heuristic that
        would need a threshold nobody could defend on a client's data.
        """
        drop = self._train_once(frame)
        if drop:
            runlog.note(
                f"retraining without {sorted(drop)}: this corpus cannot train "
                "the level that fires when they AGREE, so every positive "
                "contribution they made would be a Splink default rather than "
                "an estimate. They stay declared and will be trained on a "
                "corpus that supports them.")
            self._dropped = sorted(drop)
            return self._train_once(frame, drop=drop, final=True)
        self._dropped = []
        return self._train_once(frame, final=True)

    def _train_once(self, frame: pd.DataFrame, drop: set | None = None,
                    final: bool = False):
        from splink import DuckDBAPI, Linker, block_on

        linker = Linker(frame, self._settings(frame, drop=drop), db_api=DuckDBAPI())

        # Prior: the chance two randomly drawn mentions co-refer. Splink defaults
        # to 1e-4, which is badly wrong for this corpus (entities recur heavily),
        # and the prior shifts every posterior. Estimate it from high-precision
        # deterministic rules -- see lambda_rules() for why the obvious choice of
        # rules was measured to be 16x wrong, and what it cost end to end.
        #
        # A failure here is NOT swallowed. Falling through to Splink's 1e-4
        # default was worth ~0.20 B-cubed F1 at the operating threshold, and it
        # did so invisibly: nothing in the run output named the prior at all.
        try:
            linker.training.estimate_probability_two_random_records_match(
                lambda_rules(), recall=CFG.ER_DETERMINISTIC_RECALL,
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not estimate the match prior (probability two random "
                f"records match): {exc}. Splink would fall back to 1e-4, which "
                "on a corpus where entities recur is roughly 4 bits of evidence "
                "removed from every edge. Fix the rules in "
                "entity_resolution.lambda_rules() for this data rather than "
                "letting the default stand."
            ) from exc

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

        cal = calibration_report(linker)
        if not final:
            # First pass exists only to discover what could not be trained.
            return set(cal["untrainable_agreement"])

        self.calibration = cal
        self.calibration["dropped_untrainable"] = getattr(self, "_dropped", [])
        self._log_calibration(self.calibration)
        if not self.calibration["fully_trained"] and CFG.ER_REQUIRE_FULLY_TRAINED:
            names = sorted(self.calibration["by_comparison"])
            raise ModelNotFullyTrained(
                f"EM left {self.calibration['n_untrained_parameters']} m/u "
                f"parameters unestimated on {names}; Splink would substitute "
                "invented defaults and report the result as a calibrated "
                "probability. Set CFG.ER_REQUIRE_FULLY_TRAINED = False to "
                "proceed with those comparisons flagged instead."
            )

        preds = linker.inference.predict(threshold_match_probability=0.01)
        df = preds.as_pandas_dataframe()
        df["uncalibrated"] = self._uncalibrated_column(df, self.calibration)
        # match_key rides along: it names the blocking rule that proposed the
        # pair, which is the only way to tell what the embedding lane added.
        keep = ["mention_id_l", "mention_id_r", "match_probability",
                "match_weight", "match_key", "uncalibrated"]

        # Persist the trained model (settings + m/u parameters) so the QA
        # viewer can later re-score any specific pair on demand via
        # linker.inference.compare_two_records() -- real Splink output,
        # computed lazily per click instead of serialized for every one of
        # the (possibly millions of) scored edges up front.
        try:
            linker.misc.save_model_to_json(str(MODEL_PATH), overwrite=True)
        except Exception:
            pass
        # Written beside the model, not inside it: Splink owns that file's
        # schema. The ingest path checks this before scoring arriving notes --
        # see check_model_current.
        SIGNATURE_PATH.write_text(
            json.dumps(model_signature(frame, set(getattr(self, "_dropped", []))),
                       indent=2), encoding="utf-8")

        return df[[c for c in keep if c in df.columns]]

    @staticmethod
    def _log_calibration(cal: dict) -> None:
        """Say the prior and the evidence ordering out loud, every run.

        The prior was wrong by 16x for as long as this resolver has existed and
        nobody caught it, because no run ever printed it. Cheap insurance.
        """
        runlog.field("match prior", f"{cal['probability_two_random_records_match']:.6f}"
                                    f"  (1 in {1 / max(cal['probability_two_random_records_match'], 1e-12):,.0f}"
                                    f" random mention pairs co-refer)")
        order = sorted(cal["agreement_weights_bits"].items(),
                       key=lambda kv: -kv[1]["match_weight_bits"])
        runlog.field("evidence", "  ".join(
            f"{k}={v['match_weight_bits']:+.1f}b" for k, v in order))
        if not cal["fully_trained"]:
            why = Counter(r["reason"] for r in cal["untrained"])
            runlog.note(
                f"{cal['n_untrained_parameters']} m/u parameters are Splink's "
                f"substitutes, not estimates "
                f"({', '.join(f'{n} {r}' for r, n in sorted(why.items()))}) "
                f"on {', '.join(sorted(cal['by_comparison']))}. Edges that "
                "landed on a substituted level are marked in "
                "same_as_edges.uncalibrated.")

    @staticmethod
    def _uncalibrated_column(df: pd.DataFrame, cal: dict) -> pd.Series:
        """Per edge: which untrained comparisons this pair actually landed on.

        An edge is only affected if its gamma for that comparison IS one of the
        substituted levels. A pair where both sides had a null npi used no npi
        parameter at all and is perfectly calibrated, so blanket-flagging every
        edge whenever any comparison is untrained would be both alarmist and
        useless for triage.
        """
        affected = cal.get("by_comparison") or {}
        hits = {}
        for name, levels in affected.items():
            g = f"gamma_{name}"
            if g in df.columns:
                hits[name] = pd.to_numeric(df[g], errors="coerce").isin(levels)
        if not hits:
            return pd.Series([None] * len(df), index=df.index, dtype=object)
        flags = pd.DataFrame(hits, index=df.index)
        names = list(flags.columns)
        # dtype=object throughout: in a float-backed Series pandas turns None
        # into NaN, and sqlite3 stores NaN as a REAL rather than NULL, so
        # "WHERE uncalibrated IS NULL" would silently miss every calibrated edge.
        return pd.Series(
            [",".join(n for n, on in zip(names, row) if on) or None
             for row in flags.to_numpy()],
            index=df.index, dtype=object)


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

    WHICH IDENTIFIERS VETO, AND WHY THE OTHERS DO NOT
    -------------------------------------------------
    Only npi, tin and ssn. The test is not "how strong is this identifier" but
    **can one entity legitimately hold two of these at once**:

        ssn      no  -- one per person, by construction
        npi/tin  mostly -- a provider can hold both a Type 1 and a Type 2 NPI,
                 which is why the corpus models IDENTIFIER_REASSIGN_RATIO and
                 why this rule stays narrow rather than becoming a cluster-scope
                 invariant (see TODO T0.3)
        vin      YES  -- a claimant can own two vehicles and a shop touches
                 hundreds. Two VINs are not a contradiction, so vin SCORES but
                 must never veto
        address  YES  -- people move, firms have branch offices
        phone    YES  -- desk, mobile, and reassignment
        email    YES  -- personal and work

    dob is the interesting omission. A person has exactly one, so it looks like
    it belongs here. It is deliberately absent: DOB binding accuracy has never
    been measured, real DOBs carry transcription errors, and T0.3 measured what
    happens when a consistency rule meets a mis-bound identifier -- the rule
    splits a CORRECT cluster, damaging the thing that was right. Adding a dob
    veto is a change to make after measuring dob binding, not before.

    A client whose data makes one of these judgements wrong -- an insurer whose
    TINs are shared across a franchise group, say -- is changing a policy, not
    fixing a bug. That is what this list being explicit is for.
    """
    # person_vs_org WAS HERE AND IS DELETED. Measured against ground truth on a
    # 60-document run:
    #
    #     1,335 edges suppressed as person_vs_org
    #     of the 1,291 with both sides labelled, 898 (69.6%) joined two mentions
    #     of the SAME ground-truth entity
    #
    # including pairs at p=1.000 and p=0.997 -- 'Elizabeth Perez' vs
    # 'Elizabeth Perez', identical surfaces, same entity, permanently
    # suppressed. It was not protecting against over-merge; it was the largest
    # single source of under-merge in the system.
    #
    # The cause is that it vetoed on `entity_class`, and comparison_specs
    # already says why that is wrong -- "a noisy derived label from our own
    # classifier, not identity evidence". The codebase had concluded the label
    # was too unreliable to SCORE with, then used it in the strongest possible
    # way: an absolute veto no probability can outweigh. A person misclassified
    # as a repair shop in one note can never again be linked to themselves.
    #
    # Removing it, same run, same edges:
    #
    #     best B-cubed F1   0.889 -> 0.920
    #     at threshold 0.45  F1 0.843 -> 0.861, recall 0.885 -> 0.937
    #     precision cost     0.804 -> 0.796
    #     entities vs 42 gold  59 -> 54
    #
    # The identifier vetoes below stay: conflicting_tin fired 36 times in the
    # same run with ZERO false vetoes. The difference is that a TIN is observed
    # evidence and entity_class is our own guess.
    #
    # If a person/organisation constraint is wanted back, it needs a signal that
    # is not a classifier output -- the entity_type/role split (diagram 06) is
    # the proposal, and it must be re-measured against this table, not assumed
    # to be safe because the previous one looked reasonable.
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
    sel = edges[edges["match_probability"] >= threshold]
    # .to_numpy() rather than .iterrows(): this runs on every threshold change
    # (interactively, from the QA viewer) as well as once per point in
    # threshold_sweep, and .iterrows() boxing each row into a Series made that
    # visibly slow at corpus scale.
    roots = blocking.connected_components(
        zip(sel["mention_id_l"].to_numpy(), sel["mention_id_r"].to_numpy()),
        mention_ids)

    groups = defaultdict(list)
    for m in mention_ids:
        groups[roots[m]].append(m)
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

    # Second candidate generator. Adds one column; the Splink settings already
    # block on it. Raises if the mention index is missing rather than quietly
    # resolving with less recall than the configuration promises.
    frame, block_stats = blocking.attach_buckets(frame)
    # Persist the assignments so an arriving note can attach to these blocks
    # instead of starting from nothing. See incremental.persist_blocks.
    if "emb_bucket" in frame.columns:
        from .incremental import persist_blocks
        persist_blocks(repo, dict(zip(frame["mention_id"], frame["emb_bucket"])))

    edges = backend.resolve(frame)
    lanes = lane_provenance(edges)

    # Suppress structurally impossible pairs.
    #
    # zip over numpy columns rather than .iterrows(): Splink can score millions
    # of pairs in seconds, and .iterrows() boxes every one into a Series. That
    # made this loop, not the record linkage, the slowest step in the pipeline.
    feat = frame.set_index("mention_id").to_dict("index")
    reasons = []
    keep_mask = []
    for la, rb in zip(edges["mention_id_l"].to_numpy(),
                      edges["mention_id_r"].to_numpy()):
        a, b = feat.get(la), feat.get(rb)
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

    # Same reason: column-wise, not row-wise. blocked_by is mapped once over the
    # distinct match_key values rather than per row.
    n_edges = len(edges)
    mk = (edges["match_key"].map(_rule_name) if "match_key" in edges.columns
          else pd.Series([None] * n_edges, index=edges.index))
    mw = (edges["match_weight"].fillna(0.0).astype(float) if "match_weight" in edges.columns
          else pd.Series([0.0] * n_edges, index=edges.index))
    unc = (edges["uncalibrated"] if "uncalibrated" in edges.columns
           else pd.Series([None] * n_edges, index=edges.index))
    repo.add_same_as_edges([
        {"mention_id_a": a, "mention_id_b": b, "probability": float(p),
         "match_weight": float(w), "backend": backend.name,
         "blocked_by": k, "uncalibrated": uc, "suppressed_reason": sr}
        for a, b, p, w, k, uc, sr in zip(
            edges["mention_id_l"].to_numpy(),
            edges["mention_id_r"].to_numpy(),
            edges["match_probability"].to_numpy(),
            mw.to_numpy(),
            mk.to_numpy(),
            unc.to_numpy(),
            edges["suppressed_reason"].to_numpy(),
        )
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
        "embedding_blocking": block_stats,
        # pairs per blocking rule; "emb_bucket" counts the ones no
        # deterministic rule proposed -- the recall net's actual yield
        "blocking_lanes": lanes,
        # The prior, the evidence ordering in bits, and any parameter EM could
        # not estimate. Reported because a calibration that lives only in a
        # config comment was measured to have drifted 16x out of true.
        "calibration": getattr(backend, "calibration", {}),
        "n_edges_uncalibrated": int(unc.notna().sum()),
    }
