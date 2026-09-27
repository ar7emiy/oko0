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


def input_paths(cfg, xf, wf):
    """The files the chosen format reads: CSV as generated, or Parquet written beside it."""
    if cfg.io_format != "parquet" or str(xf).endswith(".parquet"):
        return xf, wf
    out = []
    for f in (xf, wf):
        pq = Path(str(f)[:-4] + ".parquet")
        if not pq.exists() or pq.stat().st_mtime < Path(f).stat().st_mtime:
            pd.read_csv(f, dtype=str, keep_default_na=False, na_filter=False).to_parquet(pq, index=False)
        out.append(pq)
    return tuple(out)


IO = TableIO(CFG)
TF = None
if CFG.io_format == "delta":
    XDF, XREP, WDF, WREP, INPUT_META = IO.read_inputs()
else:
    XF, WF, TF = dataset_files(CFG, MAPS, REF)
    SW.mark("inputs ready")
    XDF, XREP, WDF, WREP, INPUT_META = IO.read_inputs(*input_paths(CFG, XF, WF))
for rep in (XREP, WREP):
    print(f"{rep['source']}: {rep['rows']:,} rows; all-empty columns: {rep['all_empty_columns'] or 'none'}; "
          f"passthrough: {rep['passthrough_columns'] or 'none'}")
print(f"inputs: {INPUT_META}")
SW.mark("1 load and validate")