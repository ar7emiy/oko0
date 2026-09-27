def assemble_outputs(pr, models, scored, xdf, cfg, truth_file=None, log=print):
    """Tables from scored results: pairs, entities, rows, claims, evidence, dedup pairs,
    sensitivity, diagnostics."""
    ents = scored["entities"]
    pairs = pd.concat([pair_table(pr, part, scored["link"][part][0], ents[part], scored["clusters"][part]["status"],
                                  scored["clusters"][part]["e_cid"], scored["clusters"][part]["w_cid"])
                       for part in ("business", "person")], ignore_index=True)
    entities = rollup_entities(pr, pairs, {part: scored["link"][part][2] for part in ("person", "business")},
                               ents, scored["clusters"], cfg)
    rows = rollup_rows(pr, entities, ents)
    claims = rollup_claims(rows, xdf.groupby("claim_id").size())
    evs = []
    for part in ("business", "person"):
        S, L = scored["link"][part][0], scored["link"][part][1]
        if len(S):
            evs.append(evidence_for(pr, part, pairs[pairs["part"] == part].reset_index(drop=True), L, S,
                                    models["link"].weights[part]))
    evidence = pd.concat(evs, ignore_index=True) if evs else pd.DataFrame(columns=EVIDENCE_COLUMNS)
    dedup = dedup_table(pr, scored["dedup"], ents)
    if len(pairs):
        best = pairs[pairs["veto"] == ""].sort_values(["part", "_e", "p", "bits"], ascending=[True, True, False, False]) \
            .groupby(["part", "_e"]).head(1)
        best = best.merge(entities[["entity_id", "prior_group"]], on="entity_id", how="left")
    else:
        best = pd.DataFrame({"part": [], "prior_group": [], "bits": []})
    sens = sensitivity(best, models["link"].prior_df, cfg)
    diag = diagnostics(pr, scored, pairs, cfg, truth_file, log=log)
    out = {"pairs": pairs, "entities": entities, "rows": rows, "claims": claims, "evidence": evidence,
           "dedup": dedup, "sens": sens, "diag": diag}
    if cfg.baseline:
        out["pairs"] = add_baseline_columns(pr, pairs, ents, cfg)
        out["baseline_raw"] = run_baseline(pr, cfg, log)
        out["baseline_matches"] = baseline_table(pr, out["baseline_raw"], rows)
    return out


def run_pipeline(xdf, wdf, maps, ref, cfg, truth_file=None, log=None, sw=None, models=None):
    """Steps 2-16 on two validated input frames; every table in a dict. `models`: reuse
    trained parameters instead of estimating them (incremental runs)."""
    log = log or (lambda *a, **k: None)
    mark = sw.mark if sw is not None else (lambda s: None)
    pr = prepare(xdf, wdf, maps, ref, cfg, log=log)
    mark("2-6 normalize, standardize addresses, breakdown, value index, category, rarity")
    if models is None:
        models = estimate_models(pr, maps, ref, cfg, wdf, log=log)
    else:
        pr.ctx.components = models["components"].get("link", {})
        pr.ctx_dedup.components = models["components"].get("dedup", {})
    mark("8-11 u, m, prior (dedup and link models)")
    scored = score_all(pr, models, cfg, log=log)
    mark("7, 12 candidates, deduplication, linking, clusters")
    out = assemble_outputs(pr, models, scored, xdf, cfg, truth_file, log)
    mark("13-14, 16 roll-ups, evidence, diagnostics")
    link_w = pd.concat([models["link"].weights["person"], models["link"].weights["business"]], ignore_index=True)
    out.update({"pr": pr, "models": models, "scored": scored, "xdf": xdf,
                "params": {"weights": models["link"].weights, "components": models["components"].get("link"),
                           "sources": models["sources"], "em": models["em_loose"], "all_weights": link_w},
                "prior_df": models["link"].prior_df})
    return out
