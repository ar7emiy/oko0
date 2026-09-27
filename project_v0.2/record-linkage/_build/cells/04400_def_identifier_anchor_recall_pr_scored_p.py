def identifier_anchor_recall(pr, scored, part):
    """Pairs sharing a valid single-holder identifier: share of them (as entity pairs) that at
    least one non-identifier rule also proposed (the name rules alone)."""
    X, W = pr.X[part], pr.W[part]
    S = scored["link"][part][0]
    ent = scored["entities"][part]
    ids = ["ssn", "npi", "dl", "license", "email", "vin", "plate"] if part == "person" else ["tin", "cnpi", "email"]
    single = pr.ctx.stats.single
    found = []
    for t in ids:
        a = pd.DataFrame({"k": X[f"id_{t}"].to_numpy(dtype=object), "l": np.arange(len(X))})
        b = pd.DataFrame({"k": W[f"id_{t}"].to_numpy(dtype=object), "r": np.arange(len(W))})
        a = a[(a["k"] != "") & a["k"].isin(single.get(t, set()))]
        b = b[b["k"] != ""]
        found.append(a.merge(b, on="k")[["l", "r"]])
    A = pd.concat(found).drop_duplicates() if found else pd.DataFrame(columns=["l", "r"])
    if not len(A) or not len(S):
        return {"part": part, "identifier_anchor_pairs": len(A), "proposed_by_name_rules": 0, "recall": float("nan")}
    A = pd.DataFrame({"e": ent.e_of[A["l"].to_numpy(dtype=np.int64)], "r": A["r"].to_numpy()}).drop_duplicates()
    rules = pd.Series(S["rules"].to_numpy(), index=pd.MultiIndex.from_arrays([S["e"], S["r"]]))
    got = rules.reindex(pd.MultiIndex.from_frame(A)).fillna("")
    name_rule = got.map(lambda s: any(x and x not in IDENTIFIER_RULES and x != "exhaustive" for x in s.split(",")))
    return {"part": part, "identifier_anchor_pairs": len(A), "proposed_by_name_rules": int(name_rule.sum()),
            "recall": float(name_rule.mean())}


def truth_pairs_eval(pr, scored, pairs, truth, part):
    """Truth pairs (x_record_id, part, w_record_id) against the run: proposed (candidate
    stage), kept, ranked first, p, basis. Each extracted row is judged through its entity."""
    X, W = pr.X[part], pr.W[part]
    ent = scored["entities"][part]
    t = truth[truth["part"] == part]
    xi = pd.Series(np.arange(len(X)), index=X["record_id"].to_numpy())
    wi = pd.Series(np.arange(len(W)), index=W["record_id"].to_numpy())
    t = t[t["x_record_id"].isin(xi.index) & t["w_record_id"].isin(wi.index)]
    if not len(t):
        return None
    e = ent.e_of[xi[t["x_record_id"]].to_numpy()]
    r = wi[t["w_record_id"]].to_numpy()
    keys = _key(e, r)
    proposed = np.isin(keys, scored["link"][part][3]["keys"])
    P = pairs[pairs["part"] == part]
    kp = P.set_index(_key(P["_e"], P["_r"])) if len(P) else pd.DataFrame(columns=["p", "rank", "basis", "rests_on_name", "cluster_status"])
    tb = kp.reindex(keys)
    out = t.copy()
    out["entity_id"] = ent.ids[e]
    out["proposed"] = proposed
    out["kept"] = tb["p"].notna().to_numpy()
    out["p"] = tb["p"].fillna(0.0).to_numpy()
    out["rank"] = tb["rank"].to_numpy()
    out["basis"] = tb["basis"].fillna("not kept").to_numpy()
    out["cluster_status"] = tb["cluster_status"].fillna("").to_numpy() if "cluster_status" in tb else ""
    return out


def truth_recall(pr, scored, pairs, truth, part):
    ev = truth_pairs_eval(pr, scored, pairs, truth, part)
    if ev is None:
        return {"part": part, "true_pairs": 0}
    k = ev[ev["kept"]]
    return {"part": part, "true_pairs": len(ev), "proposed": int(ev["proposed"].sum()),
            "recall": float(ev["proposed"].mean()), "kept": int(ev["kept"].sum()), "kept_share": float(ev["kept"].mean()),
            "true_pairs_ranked_first": int((k["rank"] == 1).sum()),
            "true_rests_on_name_kept": int(k["basis"].isin(["contextual", "name_only"]).sum()),
            "true_by_basis": k["basis"].value_counts().to_dict(),
            "true_p_ge_0.5": int((k["p"] >= 0.5).sum()), "true_p_ge_0.9": int((k["p"] >= 0.9).sum()),
            "missed_examples": list(ev[~ev["proposed"]]["x_record_id"].head(10))}


def diagnostics(pr, scored, pairs, cfg, truth_file=None, log=print):
    d = {"anchor_recall": [identifier_anchor_recall(pr, scored, part) for part in ("person", "business")]}
    for a in d["anchor_recall"]:
        log(f"blocking recall on identifier anchors [{a['part']}]: {a.get('proposed_by_name_rules', 0)} of "
            f"{a['identifier_anchor_pairs']} also proposed by a name rule ({a['recall']:.3f})")
    d["truth"] = []
    if truth_file is not None and Path(truth_file).exists():
        truth = pd.read_csv(truth_file, dtype=str, keep_default_na=False)
        d["truth"] = [truth_recall(pr, scored, pairs, truth, part) for part in ("person", "business")]
        for t in d["truth"]:
            if t.get("true_pairs"):
                log(f"truth [{t['part']}]: {t['true_pairs']} true pairs, proposed {t['recall']:.4f}, kept "
                    f"{t['kept_share']:.4f}, ranked first {t['true_pairs_ranked_first']}, p>=0.5 {t['true_p_ge_0.5']}, "
                    f"by basis {t['true_by_basis']}")
    hist = []
    for part in ("person", "business"):
        h = scored["link"][part][3]["hist"]
        for i, b in enumerate(BASIS_ORDER):
            for j in range(len(P_BINS) - 1):
                if h[i, j]:
                    hist.append({"part": part, "basis": b, "p_from": P_BINS[j], "p_to": min(1.0, P_BINS[j + 1]),
                                 "pairs": int(h[i, j])})
    d["hist"] = pd.DataFrame(hist)
    if len(d["hist"]):
        log(d["hist"].pivot_table(index=["part", "basis"], columns="p_from", values="pairs", aggfunc="sum",
                                  fill_value=0).to_string())
    top = pairs[(pairs["basis"] == "name_only") & (pairs["veto"] == "")].sort_values("p", ascending=False).head(20) \
        if len(pairs) else pd.DataFrame()
    d["top_name_only"] = top
    if len(top):
        log("top name-only matches:")
        log(top[["extracted_name", "watchlist_name", "watchlist_record_id", "p", "bits"]].to_string(index=False))
    d["scored_pairs"] = {part: scored["link"][part][3]["scored"] for part in ("person", "business")}
    d["dedup"] = {part: {"extracted_parties": len(pr.X[part]), "entities": len(scored["entities"][part].ids),
                         "pooled_entities": int((scored["entities"][part].size > 1).sum()),
                         "largest": int(scored["entities"][part].size.max()) if len(scored["entities"][part].size) else 0,
                         "refused_links": scored["entities"][part].refused,
                         "scored_pairs": scored["dedup"][part][1]["scored"]}
                  for part in ("person", "business")}
    return d


def _m(rows, section, key, value, source="", pairs="", lo="", hi="", note=""):
    rows.append({"section": section, "key": key, "value": value, "source": source, "pairs": pairs,
                 "ci_low": lo, "ci_high": hi, "note": note})


def build_manifest(cfg, input_meta, ref, input_reports, pr, models, sens, scored, diag, sw, selfcheck=None,
                   io_info=None):
    rows = config_records(cfg)
    _m(rows, "run", "run_id", (io_info or {}).get("run_id", ""), "TableIO", note="stamps every Delta row this run writes")
    rows.append({"section": "version", "key": "matching_core", "value": CORE_VERSION, "source": "notebook"})
    for k, v in input_meta.items():
        _m(rows, "input", k, v if isinstance(v, (int, float, str)) else json.dumps(v, default=str), "read")
    for rep in input_reports:
        for k in ("rows", "all_empty_columns", "added_columns", "passthrough_columns"):
            _m(rows, "input", f"{rep['source']}.{k}", json.dumps(rep[k]), "load")
    for k, v in (io_info or {}).items():
        _m(rows, "io", k, v if isinstance(v, (int, float, str)) else json.dumps(v, default=str), "table I/O")
    for _, r in ref["hash_checks"].iterrows():
        _m(rows, "reference", r["file"], r["actual"], "SOURCES.md", note=r["status"])
    _m(rows, "reference", "rarity_source", json.dumps(pr.reports["rarity_source"]), "Rarity")
    for k in ("parties", "rows", "address_standardizer"):
        _m(rows, "breakdown", k, json.dumps(pr.reports[k], default=str), "breakdown")
    for _, r in pr.reports["empty_rows_extracted"].iterrows():
        _m(rows, "data_quality", "empty_row.extracted", r["record_id"], "breakdown",
           note="no name, business name, TIN or clinic NPI: no party")
    _m(rows, "data_quality", "empty_rows.watchlist", len(pr.reports["empty_rows_watchlist"]), "breakdown")
    for _, r in pr.reports["invalid_values"].iterrows():
        _m(rows, "data_quality", f"invalid.{r['type']}.{r['reason']}", int(r["values"]), "normalize")
    junk = pr.vi[pr.vi["junk"] & pr.vi["valid"]]
    for _, r in junk.iterrows():
        _m(rows, "data_quality", f"junk.{r['type']}", r["value"], "value index", note=r["junk_reason"])
    _m(rows, "data_quality", "category_mismatch", pr.reports["category_mismatch"], "category",
       note="given category disagrees with an inferred one")
    if pr.reports["unmapped"] is not None:
        for _, r in pr.reports["unmapped"].iterrows():
            _m(rows, "unmapped", f"{r['source_field']}:{r['value']}", int(r["parties"]), "category_map.csv", note="-> unknown")
    for part in ("person", "business"):
        D = scored["link"][part][3]
        for rep in D["report"]:
            _m(rows, "blocking", f"{part}.{rep['rule']}", rep["pairs_after_refine"], "key counts before indexing",
               rep["pairs_before_refine"], note=(f"oversized keys {rep['oversized_keys']}, dropped {rep['dropped_keys']} "
                                                  f"({rep['dropped_pairs']} pairs) {rep['dropped_examples']}").strip())
        for k, v in D["rule_counts"].items():
            _m(rows, "blocking.proposed", f"{part}.{k}", v, "indexing (entity x watchlist pairs)")
        _m(rows, "blocking.proposed", f"{part}.scored_pairs", D["scored"], "indexing",
           note=f"{D['member_pairs']} member comparisons; exhaustive={D['exhaustive']}")
        dd = diag["dedup"][part]
        for k, v in dd.items():
            _m(rows, "dedup", f"{part}.{k}", v, "extracted-side deduplication")
    for kind in ("dedup", "link"):
        M = models[kind]
        W = pd.concat([M.weights["person"], M.weights["business"]], ignore_index=True)
        for _, r in W.iterrows():
            k = f"{kind}.{r['part']}.{r['field']}.{r['level']}"
            _m(rows, "m", k, r["m"], r["m_source"], r["m_pairs"], r["m_lo"], r["m_hi"],
               note="; ".join(x for x in (r["flag"], r.get("m_note", ""), f"prior centre {r['m_prior_centre']:.4g} ({r['m_chain']})",
                                         f"passes {r['m_passes']}") if x))
            _m(rows, "u", k, r["u"], r["u_source"], r["u_pairs"],
               note=(f"{r.get('u_method', '')}; value-specific on this level: " + r["u_value_specific"]) if r["u_value_specific"] else r.get("u_method", ""))
            _m(rows, "bits", k, r["bits_field_level"], "log2(m/u), bounded", lo=r.get("bits_lo", ""), hi=r.get("bits_hi", ""),
               note=r["unstable"])
            if r["unstable"]:
                _m(rows, "weights.unstable", k, r["bits_field_level"], "bootstrap / training passes",
                   lo=r.get("bits_lo", ""), hi=r.get("bits_hi", ""), note=r["unstable"])
        for part, ps in M.passes.items():
            for p_ in ps:
                _m(rows, "m.em_passes", f"{kind}.{part}.{p_['pass'].split(':')[-1]}",
                   json.dumps({"lambda": p_.get("lambda"), "iterations": p_.get("iterations"), "converged": p_.get("converged"),
                               "patterns": p_.get("patterns"), "fields": p_.get("fields"), "excluded": p_.get("excluded"),
                               "skipped": p_.get("skipped", "")}, default=str),
                   "EM, u fixed, Dirichlet prior", p_.get("pairs", 0))
        for part, n in M.u_sample_pairs.items():
            _m(rows, "u.sample", f"{kind}.{part}", n, "random pairs behind the fuzzy levels of u")
        for _, r in M.prior_df.iterrows():
            _m(rows, "prior", f"{kind}.{r['part']}.{r['group']}", r["prior"],
               f"strict pairs {r['strict_pairs']} / recall {r['recall']:.3f} / all pairs {r['all_pairs']}",
               r["strict_pairs"], r["prior_lo"], r["prior_hi"], r["flag"])
    for k, v in (models["components"].get("link") or {}).items():
        _m(rows, "u.name_components", f"link.{k}", v, "random pairs")
    for s in models["sources"]:
        _m(rows, "m.prior_centre_sources", f"{s['part']}.{s['source']}", s["pairs"], "pairs")
    for part, e in models["em_loose"].items():
        _m(rows, "m.prior_centre_em", part, json.dumps(e), "loose anchors, EM, u fixed")
    for _, r in sens.iterrows():
        _m(rows, "sensitivity", f"{r['part']}.{r['group']}.prior_x{r['prior_multiplier']}.recall_x{r['recall_multiplier']}",
           json.dumps({k: r[k] for k in r.index if k.startswith("entities")}), f"prior {r['prior']:.3g}")
    for a in diag["anchor_recall"]:
        _m(rows, "diagnostics", f"identifier_anchor_recall.{a['part']}", a["recall"], "name rules only",
           a["identifier_anchor_pairs"])
    for t in diag["truth"]:
        _m(rows, "diagnostics", f"truth.{t['part']}", json.dumps(t, default=str), "truth file (diagnostics only)")
    for part in ("person", "business"):
        S = scored["link"][part][0]
        if len(S):
            for v, n in S.loc[S["veto"] != "", "veto"].value_counts().items():
                _m(rows, "vetoes", f"{part}.{v}", int(n), "score")
        st = scored["clusters"][part]["status"]
        if len(st):
            for v, n in pd.Series(st).value_counts().items():
                _m(rows, "clusters", f"{part}.{v}", int(n), "link clustering (pairs)")
    for r in (selfcheck or {}).get("manifest_rows", []):
        rows.append(r)
    for r in sw.rows:
        _m(rows, "timing", r["step"], r["seconds"], "wall seconds", note=f"peak {r['peak_rss_gb']} GB")
    m = pd.DataFrame(rows)
    for c in ("section", "key", "value", "source", "pairs", "ci_low", "ci_high", "note"):
        if c not in m:
            m[c] = ""
    m = m[["section", "key", "value", "source", "pairs", "ci_low", "ci_high", "note"]].fillna("")
    m["value"] = m["value"].map(lambda v: v if isinstance(v, (int, float, np.integer, np.floating)) else str(v))
    for c in ("pairs", "ci_low", "ci_high"):
        m[c] = m[c].map(lambda v: "" if (isinstance(v, float) and v != v) else v)
    return m
