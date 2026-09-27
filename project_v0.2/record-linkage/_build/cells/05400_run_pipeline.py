if CFG.incremental:
    RUN = run_incremental(XDF, WDF, MAPS, REF, CFG, IO, log=print, sw=SW)
else:
    RUN = run_pipeline(XDF, WDF, MAPS, REF, CFG, truth_file=TF, log=print, sw=SW)
PR, MODELS, SCORED = RUN["pr"], RUN["models"], RUN["scored"]
PAIRS, ENTITIES, ROWS, CLAIMS, EVIDENCE = RUN["pairs"], RUN["entities"], RUN["rows"], RUN["claims"], RUN["evidence"]
DIAG, PARAMS = RUN["diag"], RUN["params"]
WEIGHTS = weights_output(MODELS)
show = WEIGHTS[WEIGHTS["model"] == "link"][["part", "field", "level", "m", "m_lo", "m_hi", "u", "u_method",
                                             "bits_field_level", "flag"]]
print(show.to_string(index=False, max_rows=200, float_format=lambda v: f"{v:.4g}"))
print(ENTITIES.groupby(["part", "basis"]).agg(entities=("p", "size"), p_ge_05=("p", lambda s: int((s >= 0.5).sum())),
                                              p_ge_09=("p", lambda s: int((s >= 0.9).sum()))).to_string())
