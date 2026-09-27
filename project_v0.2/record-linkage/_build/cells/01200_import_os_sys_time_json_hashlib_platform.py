import os, sys, time, json, hashlib, platform, gc
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _find_root():
    here = Path.cwd()
    for p in [here, *here.parents]:
        if (p / "mappings" / "columns.csv").exists() and (p / "reference").exists():
            return p
    return here


@dataclass
class RunConfig:
    dataset: str = "synthetic"
    root: str = ""
    seed: int = 20260925
    # ---- switches (the Settings cell sets them; see README) ---------------------------------
    io_format: str = "csv"               # "csv" (default, for display) | "parquet" | "delta": inputs and every output table
    exhaustive: bool = False             # compare every same-type pair (streamed in chunks) instead of blocking
    address_standardizer: str = "usaddress"   # "usaddress" (offline) | "given" (already standardized) | "smarty"
    baseline: bool = False               # also run the user's current method (token-sort name + category gate)
    self_check: bool = True              # held-out identifier check and noise-injection test
    incremental: bool = False            # delta only: score only new or changed extracted rows, MERGE results
    # ---- u: exact levels in closed form; fuzzy levels from a very large random sample -------
    random_pairs: int = 5_000_000        # random extracted x watchlist pairs (per part, split by share)
    dedup_random_pairs: int = 5_000_000  # random extracted x extracted pairs for the deduplication model
    # ---- m -----------------------------------------------------------------------------------
    sim_records: int = 50_000            # watchlist records copied with noise (prior centre, last resort)
    anchor_pairs_per_value: int = 50     # cap per anchoring value (strict anchors)
    loose_holders: tuple = (2, 20)       # holders of a value for the loose anchor set
    em_pairs_per_pass: int = 2_000_000   # pairs one training pass may use (sampled beyond this)
    em_key_cap: int = 2_000              # a training key proposing more pairs is sampled down to this
    bootstrap_reps: int = 200            # bootstrap replicates for every m and the prior
    # ---- candidates ----------------------------------------------------------------------------
    chunk_size: int = 20_000             # extracted parties per indexing chunk
    exhaustive_pairs_per_chunk: int = 4_000_000   # pairs per chunk when exhaustive
    block_pair_cap: int = 5_000_000      # a blocking key proposing more pairs is refined by state
    sn_window: int = 7                   # sorted-neighbourhood window
    # ---- extracted-side deduplication and clusters ---------------------------------------------
    dedup_p_min: float = 0.95            # pool two extracted records at or above this p ...
    dedup_basis: tuple = ("identifier", "address", "dob", "co_party")   # ... resting on one of these
    link_cluster_p: float = 0.5          # an entity-watchlist link joins a cluster at or above this p
    # ---- keeping and output --------------------------------------------------------------------
    keep_p_floor: float = 1e-3           # keep a pair at or above this p ...
    top_k: int = 3                       # ... or among its entity's top K (ties kept) ...
    #                                      ... or when it rests on an identifier or is vetoed
    flag_p: float = 0.5                  # the workbook's flagged entities: best p at or above this
    workbook_flagged_max: int = 200_000  # flagged entities in the workbook (all in the files)
    workbook_sample_per_stratum: int = 25   # candidate pairs sampled per basis x p band
    excel_row_limit: int = 1_048_575     # data rows per sheet before a continuation sheet
    sensitivity_prior_mult: tuple = (0.1, 1.0, 10.0)
    sensitivity_recall: tuple = (0.5, 1.0)   # multiplied into the estimated recall, capped at 1
    p_bands: tuple = (0.5, 0.8, 0.9, 0.95, 0.99)
    # ---- held-out identifier check and noise-injection test ------------------------------------
    holdout_ids: tuple = ("ssn", "npi", "tin", "dl")
    holdout_mode: str = "each"           # "each": one run per identifier hidden | "all": one run, all hidden
    holdout_max_holders: int = 2         # truth only from values held under at most this many holders
    holdout_min_pairs: int = 5           # identifiers with fewer true pairs are not run
    noise_sources: int = 2_000           # watchlist records copied with noise
    noise_max_copies: int = 3            # 1..this many noisy copies of each (tests the deduplication too)
    noise_decoys: int = 2_000            # fictional parties not on the list
    # ---- baseline: the user's current method (defaults ASSUMED until the user supplies theirs) -
    baseline_threshold: float = 90.0     # rapidfuzz token_sort_ratio at or above: a match
    baseline_strip_legal: bool = True    # drop legal suffixes (INC, LLC, PC ...)
    baseline_strip_titles: bool = True   # drop titles and credentials (DR, MD, JR ...)
    baseline_include_middle: bool = False
    baseline_gate_missing: str = "block"  # a pair with a missing category: "block" | "pass"
    # ---- address standardization (SmartyStreets: never called without credentials) -------------
    smarty_url: str = "https://us-street.api.smarty.com/street-address"
    smarty_batch: int = 100
    # ---- Delta Lake (B1.1) -----------------------------------------------------------------------
    delta_catalog: str = ""              # Unity Catalog catalog ('' = none)
    delta_schema: str = "record_linkage"  # schema (database) of the output tables
    delta_path_root: str = ""            # use paths (e.g. /Volumes/cat/schema/vol/rl) instead of table names
    delta_extracted_table: str = "extracted_entities"
    delta_watchlist_table: str = "watchlist"
    delta_output_prefix: str = "rl_"
    delta_gold_labels_table: str = "rl_gold_labels"   # placeholder for B2 (gold labels); read by nothing here
    delta_full_refresh: bool = False     # incremental mode: ignore the saved state once
    # ---- synthetic and benchmark sizes ---------------------------------------------------------
    synth_persons: int = 2_000
    synth_businesses: int = 500
    leie_noisy_copies: int = 3_000
    leie_fictional: int = 3_000
    scale_watchlist: int = 1_000_000
    scale_extracted: int = 300_000
    core: CoreParams = field(default_factory=CoreParams)

    @property
    def paths(self):
        r = Path(self.root)
        return {"root": r, "mappings": r / "mappings", "reference": r / "reference",
                "data": r / "data", "out": r / "out" / self.dataset, "review": r / "review",
                "notebook": r / "record_linkage.ipynb", "tables": r / "out" / self.dataset / "tables",
                "smarty_cache": r / "data" / "smarty_cache.json"}


def _env_bool(name, default):
    v = os.environ.get(name)
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


def make_config(dataset=None, **overrides):
    """The run configuration. Dataset presets first, then environment switches (RL_IO_FORMAT,
    RL_EXHAUSTIVE, RL_BASELINE, RL_ADDRESS_STANDARDIZER, RL_SELF_CHECK, RL_INCREMENTAL), then
    explicit overrides."""
    ds = dataset or os.environ.get("RL_DATASET", "synthetic")
    cfg = RunConfig(dataset=ds, root=str(_find_root()))
    if ds == "synthetic":
        cfg.random_pairs = cfg.dedup_random_pairs = 1_000_000
        cfg.noise_sources, cfg.noise_decoys = 800, 800
    elif ds == "leie":
        cfg.random_pairs = cfg.dedup_random_pairs = 5_000_000
    elif ds == "scale":
        cfg.random_pairs = cfg.dedup_random_pairs = 10_000_000
    cfg.io_format = os.environ.get("RL_IO_FORMAT", cfg.io_format)
    cfg.exhaustive = _env_bool("RL_EXHAUSTIVE", cfg.exhaustive)
    cfg.baseline = _env_bool("RL_BASELINE", cfg.baseline)
    cfg.address_standardizer = os.environ.get("RL_ADDRESS_STANDARDIZER", cfg.address_standardizer)
    cfg.self_check = _env_bool("RL_SELF_CHECK", cfg.self_check)
    cfg.incremental = _env_bool("RL_INCREMENTAL", cfg.incremental)
    for k, v in overrides.items():
        if not hasattr(cfg, k):
            raise AttributeError(f"RunConfig has no setting {k!r}")
        setattr(cfg, k, v)
    if cfg.io_format not in ("csv", "parquet", "delta"):
        raise ValueError(f"io_format must be csv, parquet or delta, not {cfg.io_format!r}")
    if cfg.address_standardizer not in ("usaddress", "given", "smarty"):
        raise ValueError(f"address_standardizer must be usaddress, given or smarty, not {cfg.address_standardizer!r}")
    for key in ("data", "out", "review"):
        cfg.paths[key].mkdir(parents=True, exist_ok=True)
    return cfg


def config_records(cfg):
    """The run configuration as manifest rows."""
    d = asdict(cfg)
    core = d.pop("core")
    rows = [{"section": "config", "key": k, "value": json.dumps(v) if not isinstance(v, str) else v,
             "source": "RunConfig"} for k, v in d.items()]
    rows += [{"section": "config.core", "key": k, "value": json.dumps(v), "source": "CoreParams"}
             for k, v in core.items()]
    return rows


class Stopwatch:
    """Wall time and peak resident memory per step (peak sampled after each step)."""

    def __init__(self):
        self.t0 = time.time()
        self.rows = []
        self._last = self.t0
        try:
            import psutil
            self._proc = psutil.Process()
        except ImportError:
            self._proc = None
        self.peak = 0

    def rss(self):
        if self._proc is None:
            return 0
        try:
            info = self._proc.memory_info()
            peak = getattr(info, "peak_wset", None) or info.rss   # Windows: peak working set
            return max(info.rss, peak)
        except Exception:
            return 0

    def mark(self, step):
        now = time.time()
        r = self.rss()
        self.peak = max(self.peak, r)
        self.rows.append({"step": step, "seconds": round(now - self._last, 2),
                          "elapsed": round(now - self.t0, 2), "peak_rss_gb": round(self.peak / 1e9, 3)})
        self._last = now
        print(f"[{now - self.t0:7.1f}s  peak {self.peak / 1e9:5.2f} GB] {step}")