# %% [markdown]
# ## Run
#
# The cells below run the steps in order on the dataset chosen in Setup. Each prints what it
# did; the timing and peak memory of every step go to the manifest.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.load import *
from wlink.explode import *
from wlink.category import *
from wlink.simulate import *
from wlink.synth import *
from wlink.leie import *
from wlink.prepare import *
from wlink.candidates import *
from wlink.params import *
from wlink.score import *
from wlink.output import *
from wlink.diagnostics import *

CFG = make_config()
PATHS = CFG.paths
SW = Stopwatch()
print(f"dataset: {CFG.dataset}   root: {PATHS['root']}   out: {PATHS['out']}")
print(f"python {platform.python_version()}  pandas {pd.__version__}  numpy {np.__version__}  "
      f"recordlinkage {rl.__version__}  matching core v{CORE_VERSION}")
MAPS = load_mappings(PATHS["mappings"])
REF = load_reference(PATHS["reference"], CFG.core)
print(REF["hash_checks"][["file", "status"]].to_string(index=False))
SW.mark("setup: mappings and reference tables")

# %% [markdown]
# ### Inputs for this run
#
# `synthetic` and `scale` generate their files into `data/` (with a truth file beside them);
# `leie` exports the raw LEIE into `data/leie_watchlist.csv` and builds the extracted test set;
# `files` reads `RL_EXTRACTED` and `RL_WATCHLIST`. The truth file is read only by the
# diagnostics and self-tests.

# %%


def dataset_files(cfg, maps, ref):
    d = cfg.paths["data"]
    ds = cfg.dataset
    if ds == "files":
        return Path(os.environ["RL_EXTRACTED"]), Path(os.environ["RL_WATCHLIST"]), None
    xf, wf, tf = d / f"{ds}_extracted.csv", d / f"{ds}_watchlist.csv", d / f"{ds}_truth.csv"
    if ds == "synthetic" and not (xf.exists() and wf.exists() and tf.exists()):
        X, W, truth, _, _ = make_dataset(cfg.synth_persons, cfg.synth_businesses, 5000, ref,
                                         maps["simulation_noise"], cfg.seed)
        X.to_csv(xf, index=False); W.to_csv(wf, index=False); truth.to_csv(tf, index=False)
    elif ds == "leie" and not (xf.exists() and wf.exists() and tf.exists()):
        raw = d / "LEIE_UPDATED.csv"
        if not raw.exists():
            import urllib.request
            req = urllib.request.Request(LEIE_URL, headers={"User-Agent": "record-linkage/1.0"})
            raw.write_bytes(urllib.request.urlopen(req, timeout=300).read())
        W = export_leie(raw, wf)
        X, truth, _ = leie_test_set(W, ref, maps["simulation_noise"], cfg.seed, cfg.leie_noisy_copies,
                                    cfg.leie_fictional)
        X.to_csv(xf, index=False); truth.to_csv(tf, index=False)
    elif ds == "scale" and not (xf.exists() and wf.exists() and tf.exists()):
        X, W, truth = make_scale_set(cfg, maps, ref)
        X.to_csv(xf, index=False); W.to_csv(wf, index=False); truth.to_csv(tf, index=False)
    return xf, wf, tf


XF, WF, TF = dataset_files(CFG, MAPS, REF)
SW.mark("inputs ready")
XDF, XREP = load_input(XF, "extracted")
WDF, WREP = load_input(WF, "watchlist")
INPUT_HASH = {"extracted": sha256_file(XF), "watchlist": sha256_file(WF)}
for rep in (XREP, WREP):
    print(f"{rep['source']}: {rep['rows']:,} rows; all-empty columns: {rep['all_empty_columns'] or 'none'}; "
          f"passthrough: {rep['passthrough_columns'] or 'none'}")
SW.mark("1 load and validate")

# %% [markdown]
# ### Steps 2-6: normalize, breakdown, value index, category, rarity

# %%
PR = prepare(XDF, WDF, MAPS, REF, CFG)
print(f"category disagreements (given vs inferred): {PR.reports['category_mismatch']}")
if PR.reports["unmapped"] is not None and len(PR.reports["unmapped"]):
    print(f"unmapped watchlist specialty / licence values (-> unknown): {len(PR.reports['unmapped'])}")
    print(PR.reports["unmapped"].head(10).to_string(index=False))
SW.mark("2-6 normalize, breakdown, value index, category, rarity")

# %% [markdown]
# ### Steps 8-11: u, m, prior

# %%
PARAMS = estimate_parameters(PR, MAPS, REF, CFG, WDF)
SW.mark("8-10 u and m")
PRIOR, PRIOR_DF = estimate_prior(PR, PARAMS, CFG)
WEIGHTS = pd.concat([PARAMS["weights"]["person"], PARAMS["weights"]["business"]], ignore_index=True)
show = WEIGHTS[["part", "field", "level", "m", "m_source", "m_pairs", "u", "bits_field_level", "flag"]]
print(show.to_string(index=False, max_rows=200, float_format=lambda v: f"{v:.4g}"))
SW.mark("11 prior")

# %% [markdown]
# ### Steps 7, 12: candidates and scoring (chunked)

# %%
SCORED = score_all(PR, PARAMS, PRIOR, CFG)
SW.mark("7, 12 candidates, comparisons, scoring")

# %% [markdown]
# ### Steps 13-14: roll-ups and evidence

# %%
PAIRS = pd.concat([pair_table(PR, part, SCORED[part][0]) for part in ("business", "person")], ignore_index=True)
ENTITIES = rollup_entities(PR, PAIRS, {part: SCORED[part][2] for part in ("person", "business")}, CFG)
CLAIMS = rollup_claims(ENTITIES, XDF.groupby("claim_id").size())
EVIDENCE = pd.concat([evidence_for(PR, part, pair_table(PR, part, SCORED[part][0]), SCORED[part][1],
                                   SCORED[part][0], PARAMS["weights"][part])
                      for part in ("business", "person") if len(SCORED[part][0])], ignore_index=True)
_best = PAIRS[PAIRS["veto"] == ""].sort_values(["part", "_l", "p", "bits"], ascending=[True, True, False, False]) \
    .groupby(["part", "_l"]).head(1)
_best = _best.merge(ENTITIES[["party_id", "prior_group"]],
                    left_on=_best["pair_id"].str.split("~").str[0], right_on="party_id", how="left")
SENS = sensitivity(_best, PRIOR_DF, CFG)
print(ENTITIES.groupby(["part", "basis"]).agg(entities=("p", "size"), p_ge_05=("p", lambda s: int((s >= 0.5).sum())),
                                              p_ge_09=("p", lambda s: int((s >= 0.9).sum()))).to_string())
SW.mark("13-14 roll-ups and evidence")

# %% [markdown]
# ### Step 16: diagnostics
#
# Blocking recall on identifier anchors (extracted x watchlist pairs sharing a valid
# single-holder identifier: how many would the name rules alone have proposed?); on datasets
# with a truth file, recall of the true pairs; the p histogram by basis; the 20 strongest
# name-only matches.

# %%
DIAG = diagnostics(PR, SCORED, PAIRS, CFG, TF)
SW.mark("16 diagnostics")

# %% [markdown]
# ### Step 15: workbook and manifest

# %%
MANIFEST = build_manifest(CFG, INPUT_HASH, REF, (XREP, WREP), PR, PARAMS, PRIOR_DF, SENS, SCORED, DIAG, SW)
CAND_OUT = PAIRS.drop(columns=["_l", "_r"])
TABLES = {"entities": ENTITIES, "candidates": CAND_OUT,
          "evidence": EVIDENCE if CFG.evidence_in_workbook else EVIDENCE.iloc[:0],
          "claims": CLAIMS, "manifest": MANIFEST}
save_tables(PATHS["out"], {"entities": ENTITIES, "candidates": CAND_OUT, "evidence": EVIDENCE, "claims": CLAIMS,
                           "manifest": MANIFEST}, MANIFEST)
WB_PATH = PATHS["out"] / f"record_linkage_{CFG.dataset}.xlsx"
WRITTEN = write_workbook(WB_PATH, TABLES, CFG.excel_row_limit)
SW.mark("15 workbook")
print(f"workbook: {WB_PATH}  sheets: {sum(len(v) for v in WRITTEN.values())} "
      f"({', '.join(f'{k}: {len(v)}' for k, v in WRITTEN.items())})")
print(f"total {SW.rows[-1]['elapsed']:.1f}s, peak memory {SW.peak / 1e9:.2f} GB")
(PATHS["out"] / "timing.json").write_text(json.dumps(SW.rows, indent=1), encoding="utf-8")
