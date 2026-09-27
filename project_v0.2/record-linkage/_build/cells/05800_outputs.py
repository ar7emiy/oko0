def output_tables(run, selfcheck, manifest):
    """Every full table, by output name."""
    t = {"entities": run["entities"], "rows": run["rows"], "candidates": run["pairs"], "evidence": run["evidence"],
         "claims": run["claims"], "dedup_pairs": run["dedup"], "weights": weights_output(run["models"]),
         "manifest": manifest}
    if "baseline_matches" in run:
        t["baseline_matches"] = run["baseline_matches"]
    if selfcheck:
        for k in ("bands", "funnel", "basis", "bins"):
            t[f"selfcheck_{k}"] = selfcheck[k]
        if CFG.baseline:
            t["baseline_disagreements"] = selfcheck["disagreements"]
            t["baseline_ambiguity"] = selfcheck["ambiguity"]
    return t


SW.mark("15 before writing")
MANIFEST = build_manifest(CFG, INPUT_META, REF, (XREP, WREP), PR, MODELS, RUN["sens"], SCORED, DIAG, SW,
                          SELFCHECK, IO.info)
WRITTEN_TABLES = {name: IO.write(name, df) for name, df in output_tables(RUN, SELFCHECK, MANIFEST).items()}
if CFG.io_format == "delta":
    write_run_state(IO, RUN, INPUT_META)
WB_PATH = PATHS["out"] / f"record_linkage_{CFG.dataset}.xlsx"
WRITTEN = write_workbook(WB_PATH, workbook_tables(RUN, SELFCHECK, MANIFEST, CFG), CFG.excel_row_limit)
(PATHS["out"] / "manifest.json").write_text(json.dumps(MANIFEST.to_dict("records"), indent=1, default=str), encoding="utf-8")
SW.mark("15 tables and workbook")
print(f"tables ({CFG.io_format}): " + ", ".join(f"{k} {v.get('rows', v.get('appended', ''))}" for k, v in WRITTEN_TABLES.items()))
print(f"workbook: {WB_PATH}  sheets: {sum(len(v) for v in WRITTEN.values())} "
      f"({', '.join(f'{k}: {len(v)}' for k, v in WRITTEN.items())})")
print(f"total {SW.rows[-1]['elapsed']:.1f}s, peak memory {SW.peak / 1e9:.2f} GB")
(PATHS["out"] / "timing.json").write_text(json.dumps(SW.rows, indent=1), encoding="utf-8")
