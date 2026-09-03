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
GENAI_MODEL = "gemini-3.7-flash"                # extraction / adjudication / NL planning / generation

# Per-task model routing. One model for every lane is the wrong default here:
# the lanes differ by two orders of magnitude in volume and by a lot in how much
# judgement they need, and paying flagship rates for a high-volume recall net is
# most of the bill.
#
#   gemini-3.7-flash        $0.75 / $3.75 per 1M in/out
#   gemini-3.1-flash-lite   $0.25 / $1.50   -- 3x cheaper in, 2.5x cheaper out
#
# (gemini-2.5-flash-lite is cheaper still at $0.10/$0.40 but is RETIRED on
# 16 Oct 2026, so it is not a durable choice. Rates for the 3.x line are marked
# effective to 31 Dec 2026 and then double.)
#
# WHAT MAY NOT BE DOWNGRADED WITHOUT RE-MEASURING. Identifier binding measured
# 0.969 precision in-pipeline (T1.2) and relation extraction is the evidence
# path -- both quality claims are attached to gemini-3.7-flash specifically.
# Changing the model under a measured number silently invalidates it, which is
# the same class of mistake as the ER_LINK_THRESHOLD comment that drifted out of
# true. Downgrade a lane only after re-running its measurement on the new model.
#
# `sweep` is the opposite case: highest call volume in the pipeline (one call
# per chunk, ~3 per document), and its job is to catch spans the other lanes
# missed -- a recall net, not a judgement call.
GENAI_MODEL_BY_TASK = {
    "sweep": "gemini-3.1-flash-lite",
}
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
VECTOR_METRIC = "ip"                        # IndexFlatIP (vectors are L2-normalized -> cosine)

# ---- Layer 2 blocking: the embedding recall net -----------------------------
# Deterministic blocking only proposes a pair when two mentions SHARE A KEY
# (email, npi, sorted name, soundex last name, ...). Variants that share no key
# are never scored at all, so they can never be merged no matter how good the
# comparison model is: "Bob Miller" vs "Robert Miller Jr", "Valley Auto Body"
# vs "Valley Auto Body & Paint", or an entity whose surface form differs in
# every note it appears in. Blocking recall is a hard ceiling on ER recall.
#
# The embedding lane is a SECOND candidate generator unioned with those rules:
#   mention vectors -> class-filtered k-NN -> keep edges >= EMB_BLOCK_SIM ->
#   connected components -> one bucket id per mention, blocked on like any
#   other column.
#
# It only ever PROPOSES. Splink still scores every proposed pair with the same
# EM-trained Fellegi-Sunter model, so an embedding-found link is exactly as
# auditable as a deterministic one -- and Splink's match_key records which lane
# surfaced each pair, so the lane's contribution is measurable rather than
# asserted.
EMB_BLOCK_ENABLED = True
EMB_BLOCK_TOPK = 25          # neighbors retrieved per mention before thresholding
EMB_BLOCK_SAME_CLASS = True  # a person never blocks with a repair shop

# Cosine floor for a k-NN edge to join two mentions.
#
# THIS CONSTANT IS SPECIFIC TO EMBED_MODEL. It is not a portable "how similar is
# similar" number: embedding models differ enormously in how they use the range.
# gemini-embedding-001 puts everything in a narrow band near 0.25-0.35, where a
# sentence-transformer would spread the same pairs over 0.55-0.95. A value
# carried over from another model does not merely perform worse -- it produces
# ZERO edges, and a blocking lane that proposes nothing looks exactly like a
# lane that found nothing to propose.
#
# MEASURED, not guessed. On 14 hand-labelled mentions covering the variant
# classes this lane exists for (Bob Miller / Robert Miller Jr / R. Miller,
# Valley Auto Body / Valley Auto Body & Paint / Valley Autobody, Dr. Alicia
# Reyes / Alicia Reyes MD, Karen Wu / adjuster Karen Wu), same-class pairs
# separated cleanly:
#
#     true co-referring pairs : min 0.3000  median 0.3285  max 0.3389
#     non-co-referring pairs  : min 0.2565  median 0.2709  max 0.2899
#
# The hardest false pair is 'Dr. Alicia Reyes' vs 'Dr. Alan Reyes' at 0.2899 --
# different people, shared surname, same speciality. That pair is exactly what
# Splink is for, so the floor sits below it deliberately: the lane proposes it
# and the comparison model rejects it.
#
# The margin is thin (0.30 vs 0.29). That is a real property of this embedding
# model, not a tuning failure, and it is why blocking.py raises rather than
# shrugs when the threshold falls outside the observed distribution.
# Re-run the calibration cell in notebook 04 after changing EMBED_MODEL.
EMB_BLOCK_SIM = 0.29
EMB_BLOCK_SIM_CALIBRATED_FOR = "gemini-embedding-001"
# Chars of raw note on each side of the mention folded into its vector.
# 0 = pure name+class.
#
# MEASURED, and the result was not what was assumed. Sweeping 0 / 40 / 120 over
# the labelled set described under EMB_BLOCK_SIM, separability barely moved:
#
#   window   true-pair min   false-pair max   margin
#        0          0.3000           0.2899   0.0101
#       40          0.2718           0.2622   0.0096
#      120          0.2697           0.2596   0.0101
#
# Context did NOT help disambiguate the hardest false pair ('Dr. Alicia Reyes'
# vs 'Dr. Alan Reyes' -- two real people, shared surname, same speciality),
# which was the main argument for including it. It only shifted the whole
# distribution down.
#
# So the default is 0: it is the simplest configuration, it keeps the highest
# absolute similarities, and above all it removes a coupling -- with context in
# the vector, EMB_BLOCK_SIM has to be re-calibrated whenever this number
# changes, and two knobs that must move together are two chances to move only
# one. Caveat: 14 hand-labelled mentions is a small sample. Re-measure on real
# annotated data before treating "context does not help" as settled.
EMB_BLOCK_CONTEXT_CHARS = 0
# Components above this size are DROPPED (bucket set to NULL, which Splink
# excludes from blocking) rather than emitted. A loose threshold lets components
# chain transitively -- A~B, B~C, C~D with A nothing like D -- and one runaway
# component of n mentions costs n^2/2 pairs, the same blow-up the empty-string
# address_key comment in entity_resolution.build_mention_frame describes.
# Dropping is safe: those mentions keep all nine deterministic rules. A giant
# component means the embedding signal was not discriminative there, and the
# honest response is to contribute nothing rather than to contribute noise.
EMB_BLOCK_MAX_BUCKET = 60

# ---- Layer 2 entity resolution (Splink) --------------------------------------
# Identity is a THRESHOLD-DERIVED VIEW over probability-weighted SAME_AS edges,
# not a stored merge. This is the operating point; the audit reports the whole
# precision/recall curve across thresholds rather than this single number.
# Chosen FROM THE MEASURED B-cubed CURVE (audit.bcubed_sweep), not assumed.
# The curve is flat across 0.30-0.60; we operate at 0.45 rather than at the F1
# max because the product goal is not missing connections, and the lower
# threshold yields an entity count closer to truth.
#
# 2026-09-02: this comment previously quoted "F1 0.813-0.837, 0.45 -> F1 0.825".
# Those numbers had silently become false -- measured, the curve at 0.45 was
# P 0.973 / R 0.438 / F1 0.604, splitting 42 entities into 515. The cause was
# ER_LAMBDA_RULES below, not this threshold: with the prior corrected, 0.45
# measures F1 0.800 and the curve is flat again (min F1 0.783 across 0.20-0.95),
# so this value survives unchanged. The lesson is in ER_REQUIRE_FULLY_TRAINED:
# a calibration claim that lives only in a comment will drift out of true and
# nothing will notice.
ER_LINK_THRESHOLD = 0.45
# Assumed recall of the deterministic rules used to estimate the match prior.
# Splink's 1e-4 default is far off for a corpus where entities recur heavily.
ER_DETERMINISTIC_RECALL = 0.7
# Fail the run when Splink could not estimate every m/u parameter, instead of
# letting it substitute invented defaults. Default False because this corpus
# genuinely cannot train the npi comparison -- 7 of 922 mentions carry an NPI --
# and refusing to run would be worse than running with that one comparison
# flagged. Set True in an environment where uncalibrated evidence is
# unacceptable; the untrained set is reported either way, per-run and per-edge.
ER_REQUIRE_FULLY_TRAINED = False
ER_THRESHOLD_SWEEP = (0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90)

# The legacy resolver thresholds and the RES_WEIGHTS weighted-feature model
# that used to sit here are gone with the v1 resolver. Splink learns its own
# m/u parameters by EM, so hand-tuned feature weights are not just unused --
# they would be a second, contradictory answer to a question the model now
# answers from the data.

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
# Mention vectors, one row per mention. Named for what they hold: these are
# NOT entity vectors -- entities do not exist yet when this index is built,
# because resolving them is what the index is for.
MENTION_INDEX_FILENAME = "mentions.faiss"
MENTION_META_FILENAME = "mentions_faiss_meta.parquet"
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
NER_BACKEND = "gliner"        # gliner (production) | deterministic (research/offline only)
GLINER_MODEL = "urchade/gliner_multi-v2.1"   # required: NER_BACKEND="gliner" fails loudly if unreachable
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
