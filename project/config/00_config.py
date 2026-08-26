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

# ---- Corpus generation targets ----------------------------------------------
N_CLAIMS = 300                             # ~300 claims
NOTES_PER_CLAIM_MIN = 4
NOTES_PER_CLAIM_MAX = 11                   # -> ~1,500-3,000 notes total
N_GROUND_TRUTH_ENTITIES_MIN = 120
N_GROUND_TRUTH_ENTITIES_MAX = 200

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

# ---- Resolution thresholds / bands ------------------------------------------
RES_LOW_BAND = 0.30                         # below -> auto no-link
RES_HIGH_BAND = 0.90                        # above -> auto link
RES_ADJUDICATE_LOW = 0.30                   # [low, high] ambiguous band -> Gemini adjudicator
RES_ADJUDICATE_HIGH = 0.90
HUB_IDENTIFIER_MAX_ENTITIES = 8             # identifier shared by >8 provisional entities -> down-weight
HUB_DOWNWEIGHT = 0.15                       # multiplier applied to a hub identifier's contribution
CLUSTER_LINK_THRESHOLD = 0.55              # correlation-clustering positive-edge threshold

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
    "embed_cosine": 1.0,          # banded cosine
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
