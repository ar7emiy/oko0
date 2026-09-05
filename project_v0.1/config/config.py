# =============================================================================
# config.py -- the ONLY place a model name, threshold, seed or path is defined.
#
# Every value carried over from v0 is annotated with what it was measured at.
# A value with no measurement note is a default nobody has tested; treat it as
# an open question, not a decision.
# =============================================================================

# ---- Models -----------------------------------------------------------------
GENAI_MODEL = "gemini-3.7-flash"
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768

# Per-task routing. Lanes differ by orders of magnitude in call volume and in
# how much judgement they need. MEASURED: identifier binding scores 0.989 on
# flash vs 0.982 on flash-lite -- but flash-lite's errors are role descriptors
# ("Claimant", "the insured") that the prompt explicitly forbids, and it
# declines far less often while being no more accurate. Binding stays on flash.
# `sweep` is the opposite case: highest volume, and a recall net rather than a
# judgement call.
GENAI_MODEL_BY_TASK = {
    "sweep": "gemini-3.1-flash-lite",
}

GENAI_API_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY")
GENAI_MAX_WORKERS = 8
GENAI_MAX_RETRIES = 4          # with exponential backoff -- see genai.generate_json
GENAI_CACHE_ENABLED = True
GENAI_CACHE_DIRNAME = "genai_cache"

# ---- Determinism ------------------------------------------------------------
SEED = 20260826

# ---- Chunking ---------------------------------------------------------------
CHUNK_TOKENS = 300
CHUNK_OVERLAP_RATIO = 0.5
TOKENS_PER_WORD = 1.3

# ---- Span detection ---------------------------------------------------------
NER_BACKEND = "gliner"         # no silent fallback; an unreachable model raises
GLINER_MODEL = "urchade/gliner_multi-v2.1"
GLINER_THRESHOLD = 0.35
NER_LABELS = (
    "person", "organization", "medical_provider", "law_firm", "repair_shop",
    "address", "phone", "email", "identifier", "date", "medical_condition",
    "procedure", "monetary_amount",
)

SWEEP_ENABLED = True
SWEEP_MIN_TOKEN_LEN = 3
SWEEP_MAX_CANDIDATES_PER_CHUNK = 40

# ---- Coreference ------------------------------------------------------------
# MEASURED at ~43% accuracy in v0 -- the weakest component by a wide margin.
# Carried over unchanged so it is not silently "improved" without measurement.
# Coref output must be treated as low-confidence everywhere it is consumed.
COREF_BACKEND = "auto"
COREF_MAX_ANTECEDENT_CHARS = 600
COREF_PRONOUNS = ("he", "him", "his", "she", "her", "hers",
                  "they", "them", "their", "theirs", "it", "its")
COREF_DESCRIPTORS = (
    "the physician", "the doctor", "the provider", "the treating facility",
    "the facility", "the clinic", "the hospital", "the claimant", "the clmt",
    "the attorney", "the atty", "the counsel", "the shop", "the adjuster",
    "the insured", "the carrier", "same as above", "said provider",
)

# ---- Identity ---------------------------------------------------------------
# The core architectural decision: entities are CLAIM-SCOPED, and cross-claim
# identity is an explicit link, never a merge. See ARCHITECTURE.md.

# Bases on which two mentions may be merged WITHIN one claim. Fuzzy name
# similarity is deliberately absent. MEASURED: of 395 claims, 5 contain two
# distinct real entities whose names collide -- and all 5 collide ONLY on fuzzy
# similarity (Jaro-Winkler 0.886-0.911), none on exact match or token subset.
# Excluding fuzzy takes within-claim collisions to ZERO corpus-wide.
LOCAL_MERGE_BASES = ("exact_name", "token_subset_unambiguous", "shared_identifier")

# Identifier kinds strong enough to auto-link two claim-scoped entities.
# These carry their own validation (checksum or format) and are not reused
# across people the way a phone number or an address is.
# MEASURED: 81% of cross-claim entities carry one of these written in >=2 of
# their claims and are auto-linkable; the remaining 19% go to review.
STRONG_IDENTIFIERS = ("npi", "vin", "email", "ssn", "tin")

# Widening auto-link to these reaches 96% coverage but trades precision --
# people move, numbers get reassigned. Off by default; a per-client setting.
WEAK_IDENTIFIERS_AUTOLINK = ()          # candidates: ("phone", "address")

# Everything not auto-linked is ranked and queued for human review rather than
# guessed. Review is a first-class output, not a failure path.
REVIEW_ENABLED = True

# ---- Paths ------------------------------------------------------------------
# v0.1 reads the SAME corpus as v0 so the two can be measured head to head on
# the same 60-document slice against the same ground truth. Point CORPUS_DIR
# elsewhere for a different corpus.
CORPUS_DIR = "../project/data"
STORE_DIRNAME = "store"
DB_FILENAME = "entities.sqlite"

# The fixed, named evaluation slice. Fixed and named on purpose: "the first N
# documents" makes numbers incomparable the moment a corpus regenerates.
EVAL_SLICE = tuple(f"DOC{i:05d}" for i in range(60))
