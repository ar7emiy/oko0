# ---- Settings --------------------------------------------------------------------------------
RL_DATASET = os.environ.get("RL_DATASET", "synthetic")        # synthetic | leie | scale | files
IO_FORMAT = os.environ.get("RL_IO_FORMAT", "csv")             # csv (default) | parquet | delta
EXHAUSTIVE = _env_bool("RL_EXHAUSTIVE", False)                # compare every same-type pair
ADDRESS_STANDARDIZER = os.environ.get("RL_ADDRESS_STANDARDIZER", "usaddress")   # usaddress | given | smarty
BASELINE = _env_bool("RL_BASELINE", False)                    # the current method, beside B1
SELF_CHECK = _env_bool("RL_SELF_CHECK", True)                 # held-out identifier check + noise test
INCREMENTAL = _env_bool("RL_INCREMENTAL", False)              # delta only
# ------------------------------------------------------------------------------------------------
CFG = make_config(RL_DATASET, io_format=IO_FORMAT, exhaustive=EXHAUSTIVE, address_standardizer=ADDRESS_STANDARDIZER,
                  baseline=BASELINE, self_check=SELF_CHECK, incremental=INCREMENTAL)
PATHS = CFG.paths
SW = Stopwatch()
print(f"dataset: {CFG.dataset}   io: {CFG.io_format}   exhaustive: {CFG.exhaustive}   addresses: "
      f"{CFG.address_standardizer}   baseline: {CFG.baseline}   self-check: {CFG.self_check}   "
      f"incremental: {CFG.incremental}\nroot: {PATHS['root']}   out: {PATHS['out']}")
print(f"python {platform.python_version()}  pandas {pd.__version__}  numpy {np.__version__}  "
      f"recordlinkage {rl.__version__}  matching core v{CORE_VERSION}")
MAPS = load_mappings(PATHS["mappings"])
REF = load_reference(PATHS["reference"], CFG.core)
print(REF["hash_checks"][["file", "status"]].to_string(index=False))
SW.mark("setup: mappings and reference tables")
