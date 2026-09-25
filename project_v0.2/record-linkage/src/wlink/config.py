# %% [markdown]
# ## 0 · Setup
#
# One `RunConfig` holds every path, seed, sample size, chunk size, cap, floor and K; the
# matching core's own numbers sit inside it as `core` (`CoreParams`). The manifest dumps both.
# No threshold appears anywhere else.
#
# The dataset is chosen with the environment variable `RL_DATASET`:
#
# | Value | Watchlist | Extracted |
# |---|---|---|
# | `synthetic` (default) | fictional, ~5,000 rows | fictional, ~3,000 rows with ~45 hand-written edge cases |
# | `leie` | OIG LEIE (84,001 rows), exported locally into gitignored `data/` | noisy copies of 3,000 LEIE rows + 3,000 fictional parties |
# | `scale` | 1,000,000 fictional rows | 300,000 fictional rows |
# | `files` | `RL_WATCHLIST` | `RL_EXTRACTED` |
#
# **Where Splink would do better.** Splink's settings dictionary is a declarative, versioned
# model: blocking rules, comparisons and trained parameters serialize to one JSON and reload.
# Here the configuration is a dataclass and the trained parameters live in the manifest; a
# saved model cannot yet be reloaded to score new data without re-estimating.

# %%
import os, sys, time, json, hashlib, platform, gc
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
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
    # sample sizes
    random_pairs: int = 1_000_000        # random extracted x watchlist pairs for u (per part, split by share)
    sim_records: int = 50_000            # watchlist records copied with noise for simulated m
    anchor_pairs_per_value: int = 50     # cap per anchoring value (strict anchors)
    loose_holders: tuple = (2, 20)       # holders of a value for the loose anchor set
    # candidates
    chunk_size: int = 20_000             # extracted parties per indexing chunk
    block_pair_cap: int = 200_000        # a blocking key proposing more pairs is refined by state
    sn_window: int = 5                   # sorted-neighbourhood window
    # keeping and output
    keep_p_floor: float = 1e-3           # keep a pair at or above this p ...
    top_k: int = 3                       # ... or among its entity's top K (ties kept) ...
    #                                      ... or when it rests on an identifier or is vetoed
    excel_row_limit: int = 1_048_575     # data rows per sheet before a continuation sheet
    evidence_in_workbook: bool = True
    sensitivity_prior_mult: tuple = (0.1, 1.0, 10.0)
    sensitivity_recall: tuple = (0.5, 1.0)   # multiplied into the estimated recall, capped at 1
    p_bands: tuple = (0.5, 0.8, 0.9)
    # synthetic and benchmark sizes
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
                "notebook": r / "record_linkage.ipynb"}


def make_config(dataset=None, **overrides):
    ds = dataset or os.environ.get("RL_DATASET", "synthetic")
    cfg = RunConfig(dataset=ds, root=str(_find_root()))
    if ds == "leie":
        cfg.random_pairs = 2_000_000
    elif ds == "scale":
        cfg.random_pairs = 5_000_000
    for k, v in overrides.items():
        setattr(cfg, k, v)
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
