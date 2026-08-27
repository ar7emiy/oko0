# =============================================================================
# 00_config.py  --  SINGLE SOURCE OF TRUTH for the entity-intelligence POC.
#
# Every model name, path, seed, threshold and scoring weight lives here and
# ONLY here. Nothing else in the codebase may hardcode a model string, a
# threshold, or an absolute path. The orchestration notebook echoes this file
# at the top of every run.
#
# This is a plain Python module (not a package) loaded via runpy by
# src/settings.py so that a single edit here changes the whole system.
# =============================================================================

# ---- GenAI models (the ONLY place these strings may appear) -----------------
# NOTE: these strings are intentionally the *only* hardcoded model identifiers
# in the repo. src/leakage_guard.py + tests assert no other source file names a
# model. Change these freely; nothing downstream hardcodes them.
GENAI_MODEL = "gemini-3.7"                 # extraction / adjudication / NL planning / generation
EMBED_MODEL = "gemini-embedding-001"       # Gemini embedding endpoint
EMBED_DIM = 768                            # embedding dimensionality (index is built to this)

# ---- Determinism ------------------------------------------------------------
SEED = 20260826                            # global seed; corpus is reproducible from this

# =============================================================================
# CORPUS v2 -- fixture shaped to match production data
#
# v1 notes averaged ~65 words and were 34% rigid template, with claim-scoped
# entities and 1-2 planted cross-claim cases. That made every downstream number
# unreliable. v2 rebuilds the fixture around the real shape: an
# occurrence -> claim -> note hierarchy, 250-500 word predominantly free-text
# notes, and pervasive cross-claim entity overlap.
# =============================================================================
MANIFEST_SCHEMA_VERSION = 2

N_OCCURRENCES = 240                        # occurrences spawn 1-4 claims each
# claims per occurrence: mostly 1-2 (multi-party incidents spawn more)
CLAIMS_PER_OCCURRENCE_WEIGHTS = {1: 0.52, 2: 0.31, 3: 0.12, 4: 0.05}
TARGET_NOTES = 2000                        # total notes across all claims
NOTES_PER_CLAIM_MIN = 3
NOTES_PER_CLAIM_MAX = 9

# ---- note length / composition ----------------------------------------------
NOTE_WORDS_MIN = 250
NOTE_WORDS_MAX = 500
# Note *form* mix. v1 was template-dominant; real notes are narrative-dominant.
NOTE_FORM_WEIGHTS = {
    "narrative": 0.50,        # pure adjuster prose, multiple paragraphs
    "narrative_email": 0.27,  # prose + an email thread with quoted history
    "mixed": 0.16,            # small structured header, then prose
    "template_heavy": 0.07,   # the legacy structured form (now the minority)
}

# ---- entity population -------------------------------------------------------
# The claimant pool is sized from the CLAIM COUNT (most claimants appear once,
# so you need roughly as many claimants as claims). The professional pools are
# sized independently and are deliberately much smaller than the claim count --
# that size difference is what produces realistic recurrence.
N_ATTORNEYS = 62
N_PROVIDERS = 74
N_REPAIR_SHOPS = 40
N_ADJUSTERS = 44

# Recurrence is power-law, not uniform: a flat distribution would not stress
# resolution or hub handling at all. Zipf exponent: weight(rank i) = 1/(i+1)^a,
# so a LOWER alpha is flatter and a HIGHER alpha concentrates on the top ranks.
# Every class is additionally capped (FANOUT_MAX_SHARE) so no single entity can
# swallow an implausible share of the corpus.
FANOUT_ALPHA = {
    "attorney": 1.10,         # a few high-volume firms carry many files
    "medical_provider": 1.10, # a few high-volume practices
    "repair_shop": 1.30,      # moderate (geography caps concentration)
    "adjuster": 1.00,         # caseload spread, not a network signal
}
FANOUT_MAX_SHARE = 0.10       # no entity appears on more than 10% of claims

# Claimants are allocated explicitly rather than sampled, because the intended
# shape is "almost everyone appears once" with a short tail -- a Zipf draw
# produces a runaway head instead.
CLAIMANT_POOL_RATIO = 0.86    # claimants per claim; <1 forces some reuse
CLAIMANT_REPEAT_SHARE = 0.16  # share of claimants who appear on 2-4 claims
CLAIMANT_MAX_CLAIMS = 4

# ---- coreference planting ----------------------------------------------------
# Anaphora chains are what test the "hopping" failure mode. hops=1 points
# straight at a named mention; hops>=2 points at another anaphor that points
# back to the name.
COREF_CHAINS_PER_NOTE = (0, 4)
COREF_MAX_HOPS = 3
COREF_DESCRIPTOR_RATIO = 0.40   # share of anaphors that are vague descriptors

# ---- identifier planting -----------------------------------------------------
IDENTIFIER_KINDS = ("address", "phone", "email", "npi", "tin", "ssn", "vin")
# share of identifier mentions deliberately emitted with NO name nearby, so
# identifier-first resolution is genuinely testable
# Chance a note carries a paragraph whose identifier mention has NO name near
# it. (This is a per-note rate, not the resulting share of identifier mentions;
# the achieved share is reported by the generator.)
ORPHAN_PARAGRAPH_CHANCE = 0.35
IDENTIFIER_REASSIGN_RATIO = 0.10   # identifiers that change hands over time

# ---- event planting ----------------------------------------------------------
EVENT_TYPES = (
    "motion_filed", "deposition_taken", "demand_sent", "suit_filed",
    "ime_performed", "procedure_performed", "records_produced",
    "payment_issued", "reserve_set", "estimate_written", "siu_referral",
    "coverage_denied", "settlement_reached", "inspection_completed",
)
EVENTS_PER_CLAIM = (1, 5)

# ---- open-vocabulary relationships ------------------------------------------
# Deliberately beyond the four role types: a closed set drops or force-fits
# these, which is exactly the failure being corrected.
RELATION_TYPES = (
    "represents", "treats", "repairs", "adjusts",           # core roles
    "witnessed", "referred", "co_counsel", "supervises",
    "related_to", "subcontracts_to", "opposing_counsel",
    "employed_by", "billed", "examined",
)

# ---- Runtime mode -----------------------------------------------------------
# The system runs against the real Gemini API when an API key is present in the
# environment (GEMINI_API_KEY / GOOGLE_API_KEY / Colab secret). When absent it
# transparently falls back to a DETERMINISTIC OFFLINE stub so the full pipeline
# and every research invariant can be executed and verified without network or
# credentials (e.g. in CI). See DECISIONS.md ("Offline determinism").
# Force a mode with GENAI_MODE=online|offline if desired.
GENAI_API_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY")

# ---- Concurrency / caching --------------------------------------------------
GENAI_MAX_WORKERS = 8                       # parallel Gemini calls
GENAI_MAX_RETRIES = 4
GENAI_TIMEOUT_S = 90
GENAI_CACHE_ENABLED = True                  # cache keyed by (model, prompt_hash)

# ---- Vector search ----------------------------------------------------------
EMBED_TOPK = 50                             # class-filtered embedding candidate pass
VECTOR_METRIC = "ip"                        # IndexFlatIP (vectors are L2-normalized -> cosine)

# ---- Layer 2 entity resolution (Splink) --------------------------------------
# Identity is a THRESHOLD-DERIVED VIEW over probability-weighted SAME_AS edges,
# not a stored merge. This is the operating point; the audit reports the whole
# precision/recall curve across thresholds rather than this single number.
# Chosen FROM THE MEASURED B-cubed CURVE (audit.bcubed_sweep), not assumed.
# The curve is flat across 0.30-0.60 (F1 0.813-0.837); we operate at 0.45
# (P 0.818 / R 0.833, F1 0.825) rather than the F1 max at 0.60 (F1 0.837)
# because the product goal is not missing connections, and the lower threshold
# yields an entity count closer to truth. At the intuitive 0.90 precision is
# 0.997 but recall collapses to 0.106 -- the true-match probability mass sits
# in 0.5-0.9, which is exactly why identity is a threshold-derived view.
ER_LINK_THRESHOLD = 0.45
# Assumed recall of the deterministic rules used to estimate the match prior.
# Splink's 1e-4 default is far off for a corpus where entities recur heavily.
ER_DETERMINISTIC_RECALL = 0.7
ER_THRESHOLD_SWEEP = (0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90)

# ---- Legacy resolver thresholds (superseded by Splink) ----------------------
RES_LOW_BAND = 0.30                         # below -> auto no-link
RES_HIGH_BAND = 0.90                        # above -> auto link
RES_ADJUDICATE_LOW = 0.45                   # [low, high] ambiguous band -> adjudicator
RES_ADJUDICATE_HIGH = 0.80
ADJUDICATE_MAX = 3000                       # cap adjudicator calls (online feasibility); most-uncertain first
HUB_IDENTIFIER_MAX_ENTITIES = 8             # identifier shared by >8 provisional entities -> down-weight
HUB_DOWNWEIGHT = 0.15                       # multiplier applied to a hub identifier's contribution
CLUSTER_LINK_THRESHOLD = 0.55              # correlation-clustering positive-edge threshold
# a resolved cluster may never contain two distinct validated values of these:
CLUSTER_CONSISTENT_IDS = ("emails", "npis", "tins", "ssns", "dobs")

# ---- Pairwise scoring weights (weighted feature model) ----------------------
# Feature contributions are combined as a weighted sum then squashed to [0,1].
RES_WEIGHTS = {
    "name_jw": 1.6,               # order-insensitive Jaro-Winkler over tokens
    "nickname": 0.6,              # nickname-table hit bonus
    "identifier_agree": 3.2,      # validated identifier exact agreement (NPI/TIN/SSN/email)
    "identifier_partial": 0.8,
    "identifier_conflict": -4.0,  # hard-ish penalty (also a cannot-link rule)
    "address_exact": 1.4,
    "address_partial": 0.5,
    "phone_agree": 1.1,
    "dob_agree": 1.2,
    "dob_conflict": -3.0,
    "embed_cosine": 0.5,          # banded cosine (recall signal; weak on its own)
    "dup_group": 2.2,             # same near-duplicate group (quoted copy of same text)
    "cooccurrence": 0.4,          # dup-deduped claim co-occurrence
    "bias": -1.1,                 # intercept
}
RES_SQUASH_SCALE = 1.0            # logistic scale for squashing weighted sum -> probability

# ---- Profiling / dedup ------------------------------------------------------
MINHASH_NUM_PERM = 64
MINHASH_SHINGLE_WORDS = 5
MINHASH_JACCARD_THRESHOLD = 0.75  # >= -> same dup_group
TEMPLATE_MIN_LABELS = 2           # a block needs >= this many label:value pairs to fingerprint

# ---- Extraction -------------------------------------------------------------
SPAN_FIDELITY_MIN_RATIO = 0.82    # fuzzy locate ratio required for grounded=1
PLACEHOLDER_BLOCKLIST = (
    "xx", "xxx", "n/a", "na", "tbd", "same as above", "___", "____",
    "_____", "unknown", "unk", "pending", "see above", "same", "-", "--",
)

# ---- Storage artifact names (under store/) ----------------------------------
DB_FILENAME = "intel.sqlite"
FAISS_INDEX_FILENAME = "entities.faiss"
FAISS_META_FILENAME = "entities_faiss_meta.parquet"
GENAI_CACHE_DIRNAME = "genai_cache"

# ---- Bitemporal survivorship tiers (higher wins) ----------------------------
SURVIVORSHIP_TIERS = {
    "validated_id": 3,   # value backed by a validated identifier
    "template_field": 2, # deterministic template-block parse
    "narrative": 1,      # LLM narrative/email extraction
}

# ---- Audit ------------------------------------------------------------------
COVERAGE_TARGET = 1.0             # 100% char coverage per doc is the target
BCUBED_REPORT = True


# =============================================================================
# LAYER 1-4 ARCHITECTURE (hybrid high-recall extraction -> ER -> dual storage
# -> per-claim agentic retrieval). All knobs for the new layers live here.
# =============================================================================

# ---- Layer 1: chunking ------------------------------------------------------
CHUNK_TOKENS = 300                  # target chunk size in tokens
CHUNK_OVERLAP_RATIO = 0.5           # 50% sliding window -> every sentence read twice
# No tiktoken dependency: we approximate tokens by whitespace words scaled by
# TOKENS_PER_WORD (GPT-family averages ~1.3 tokens/word on prose like this).
TOKENS_PER_WORD = 1.3

# ---- Layer 1: coreference ---------------------------------------------------
COREF_BACKEND = "auto"              # auto | fastcoref | rulebased | off
COREF_MAX_ANTECEDENT_CHARS = 600    # how far back to look for an antecedent
COREF_PRONOUNS = (
    "he", "him", "his", "she", "her", "hers", "they", "them", "their", "theirs", "it", "its",
)
# vague descriptors that are coreferences, not stand-alone entities
COREF_DESCRIPTORS = (
    "the physician", "the doctor", "the provider", "the treating facility",
    "the facility", "the clinic", "the hospital", "the claimant", "the clmt",
    "the attorney", "the atty", "the counsel", "the shop", "the adjuster",
    "the insured", "the carrier", "same as above", "said provider",
)

# ---- Layer 1: token-level NER ensemble --------------------------------------
NER_BACKEND = "auto"                # auto | gliner | deterministic
GLINER_MODEL = "urchade/gliner_multi-v2.1"   # only used when gliner is installed
GLINER_THRESHOLD = 0.35             # recall-first; precision recovered downstream
NER_LABELS = (
    "person", "organization", "medical_provider", "law_firm", "repair_shop",
    "address", "phone", "email", "identifier", "date", "medical_condition",
    "procedure", "monetary_amount",
)

# ---- Layer 1: verification sweep (pass 2 differential audit) ----------------
SWEEP_ENABLED = True
SWEEP_MIN_TOKEN_LEN = 3             # ignore trivially short unmapped tokens
SWEEP_MAX_CANDIDATES_PER_CHUNK = 40

# ---- Layer 3: graph store ---------------------------------------------------
GRAPH_BACKEND = "igraph"            # igraph | neo4j (neo4j = production swap)
GRAPH_FILENAME = "claims_graph.pkl"
# Restricted, domain-specific predicate schema. Generic edges (MENTIONED_IN,
# HAS_NOTE, RELATED_TO) are REJECTED -- they turn the graph into a hairy ball
# and dilute retrieval precision.
GRAPH_PREDICATES = (
    "REPRESENTED_BY",       # claimant -> attorney
    "TREATED_BY",           # claimant -> medical_provider
    "DIAGNOSED_WITH",       # claimant -> medical_condition
    "UNDERWENT_PROCEDURE",  # claimant -> procedure
    "REPAIRED_BY",          # claimant/vehicle -> repair_shop
    "ISSUED_PAYMENT",       # adjuster/carrier -> payee
    "ADJUSTED_BY",          # claim -> adjuster
    "EMPLOYED_BY",          # person -> organization (firm/shop)
    "SHARES_ADDRESS_WITH",  # entity -> entity
    "SHARES_PHONE_WITH",    # entity -> entity
    "SHARES_IDENTIFIER_WITH",
    "ALLEGES",              # entity -> allegation text node
    "PARTY_TO",             # entity -> claim
)
GRAPH_BANNED_PREDICATES = ("MENTIONED_IN", "HAS_NOTE", "RELATED_TO", "ASSOCIATED_WITH")

# ---- Layer 3: chunk vector index -------------------------------------------
CHUNK_INDEX_FILENAME = "chunks.faiss"
CHUNK_META_FILENAME = "chunks_meta.parquet"

# ---- Layer 4: agentic retrieval --------------------------------------------
AGENT_VECTOR_TOPK = 5               # top-k chunks within the claim scope
AGENT_GRAPH_HOPS = 2                # 1-2 hop neighborhood expansion
AGENT_MAX_TRIPLES = 60              # cap context handed to the synthesizer
AGENT_ENFORCE_CLAIM_SCOPE = True    # hard filter; cross-claim reads are impossible
