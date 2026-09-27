import time
cfg = make_config("selftest", random_pairs=150_000, dedup_random_pairs=150_000, sim_records=4_000, chunk_size=700,
                  bootstrap_reps=30, address_standardizer="usaddress")
maps = load_mappings(cfg.paths["mappings"])
ref = load_reference(cfg.paths["reference"], cfg.core)
X, W, truth, edges, _ = make_dataset(400, 100, 1200, ref, maps["simulation_noise"], cfg.seed)
X, _ = validate_input(X, "X"); W, _ = validate_input(W, "W")
tf = cfg.paths["out"] / "selftest_truth.csv"
truth.to_csv(tf, index=False)
t0 = time.time()
sw = Stopwatch()
RUN = run_pipeline(X, W, maps, ref, cfg, truth_file=tf, log=print, sw=sw)
print("pipeline", round(time.time() - t0, 1), "s")
r = check_edge_cases(RUN["pr"], RUN["pairs"], RUN["rows"], RUN["scored"], edges)
print(r[~r["ok"]].to_string())
print(f"edge cases ok {int(r['ok'].sum())}/{len(r)}")
w = RUN["params"]["all_weights"]
print(w[["part", "field", "level", "m", "m_lo", "m_hi", "u", "u_method", "bits_field_level", "bits_lo", "bits_hi", "flag"]]
      .to_string(max_rows=200, float_format=lambda v: f"{v:.4g}"))
