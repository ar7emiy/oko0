# %% [markdown]
# ## 16 · Diagnostics and the manifest
#
# **Where Splink would do better.** Splink's diagnostics are charts: match-weight
# distributions, parameter-estimate comparisons across training passes, m/u per level, unlinkable
# records, cluster studio. These are tables in the manifest and printed summaries.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.candidates import IDENTIFIER_RULES
from wlink.score import P_BINS


def identifier_anchor_recall(pr, scored, part):
    """Pairs sharing a valid single-holder identifier: share proposed by at least one
    non-identifier rule (the name rules alone)."""
    X, W = pr.X[part], pr.W[part]
    S = scored[part][0]
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
    rules = pd.Series(S["rules"].to_numpy(), index=pd.MultiIndex.from_arrays([S["l"], S["r"]]))
    got = rules.reindex(pd.MultiIndex.from_frame(A)).fillna("")
    name_rule = got.map(lambda s: any(x and x not in IDENTIFIER_RULES for x in s.split(",")))
    return {"part": part, "identifier_anchor_pairs": len(A), "proposed_by_name_rules": int(name_rule.sum()),
            "recall": float(name_rule.mean())}


def truth_recall(pr, scored, pairs, truth, part):
    X, W = pr.X[part], pr.W[part]
    t = truth[truth["part"] == part]
    xi = pd.Series(np.arange(len(X)), index=X["record_id"].to_numpy())
    wi = pd.Series(np.arange(len(W)), index=W["record_id"].to_numpy())
    t = t[t["x_record_id"].isin(xi.index) & t["w_record_id"].isin(wi.index)]
    if not len(t):
        return {"part": part, "true_pairs": 0}
    keys = xi[t["x_record_id"]].to_numpy().astype(np.int64) * np.int64(1 << 32) + wi[t["w_record_id"]].to_numpy()
    proposed = np.isin(keys, scored[part][3]["keys"])
    P = pairs[pairs["part"] == part]
    kept_keys = P["_l"].to_numpy().astype(np.int64) * np.int64(1 << 32) + P["_r"].to_numpy()
    kept = np.isin(keys, kept_keys)
    kp = P.set_index(kept_keys)
    tb = kp.reindex(keys[kept])
    top1 = (tb["rank"] == 1).to_numpy()
    name_only = tb["rests_on_name"].to_numpy(dtype=bool)
    return {"part": part, "true_pairs": len(t), "proposed": int(proposed.sum()), "recall": float(proposed.mean()),
            "kept": int(kept.sum()), "kept_share": float(kept.mean()),
            "true_pairs_ranked_first": int(top1.sum()),
            "true_rests_on_name_kept": int(name_only.sum()),
            "true_by_basis": tb["basis"].value_counts().to_dict(),
            "true_p_ge_0.5": int((tb["p"] >= 0.5).sum()), "true_p_ge_0.9": int((tb["p"] >= 0.9).sum()),
            "missed_examples": list(t[~proposed]["x_record_id"].head(10))}


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
        h = scored[part][3]["hist"]
        for i, b in enumerate(BASIS_ORDER):
            for j in range(len(P_BINS) - 1):
                if h[i, j]:
                    hist.append({"part": part, "basis": b, "p_from": P_BINS[j], "p_to": min(1.0, P_BINS[j + 1]),
                                 "pairs": int(h[i, j])})
    d["hist"] = pd.DataFrame(hist)
    if len(d["hist"]):
        log(d["hist"].pivot_table(index=["part", "basis"], columns="p_from", values="pairs", aggfunc="sum",
                                  fill_value=0).to_string())
    top = pairs[(pairs["basis"] == "name_only") & (pairs["veto"] == "")].sort_values("p", ascending=False).head(20)
    d["top_name_only"] = top
    log("top name-only matches:")
    log(top[["extracted_name", "watchlist_name", "watchlist_record_id", "p", "bits"]].to_string(index=False))
    d["scored_pairs"] = {part: scored[part][3]["scored"] for part in ("person", "business")}
    return d


def build_manifest(cfg, input_hash, ref, input_reports, pr, params, prior_df, sens, scored, diag, sw):
    rows = config_records(cfg)
    rows.append({"section": "version", "key": "matching_core", "value": CORE_VERSION, "source": "notebook"})
    rows += [{"section": "input", "key": f"{k}.sha256", "value": v, "source": "file"} for k, v in input_hash.items()]
    for rep in input_reports:
        for k in ("rows", "all_empty_columns", "added_columns", "passthrough_columns"):
            rows.append({"section": "input", "key": f"{rep['source']}.{k}", "value": json.dumps(rep[k]), "source": "load"})
    for _, r in ref["hash_checks"].iterrows():
        rows.append({"section": "reference", "key": r["file"], "value": r["actual"], "source": "SOURCES.md",
                     "note": r["status"]})
    rows.append({"section": "reference", "key": "rarity_source", "value": json.dumps(pr.reports["rarity_source"]),
                 "source": "Rarity"})
    for k in ("parties", "rows"):
        rows.append({"section": "breakdown", "key": k, "value": json.dumps(pr.reports[k]), "source": "breakdown"})
    for _, r in pr.reports["empty_rows_extracted"].iterrows():
        rows.append({"section": "data_quality", "key": "empty_row.extracted", "value": r["record_id"],
                     "source": "breakdown", "note": "no name, business name, TIN or clinic NPI: no party"})
    rows.append({"section": "data_quality", "key": "empty_rows.watchlist", "value": len(pr.reports["empty_rows_watchlist"]),
                 "source": "breakdown"})
    for _, r in pr.reports["invalid_values"].iterrows():
        rows.append({"section": "data_quality", "key": f"invalid.{r['type']}.{r['reason']}", "value": int(r["values"]),
                     "source": "normalize"})
    junk = pr.vi[pr.vi["junk"] & pr.vi["valid"]]
    for _, r in junk.iterrows():
        rows.append({"section": "data_quality", "key": f"junk.{r['type']}", "value": r["value"],
                     "source": "value index", "note": r["junk_reason"]})
    rows.append({"section": "data_quality", "key": "category_mismatch", "value": pr.reports["category_mismatch"],
                 "source": "category", "note": "given category disagrees with an inferred one"})
    if pr.reports["unmapped"] is not None:
        for _, r in pr.reports["unmapped"].iterrows():
            rows.append({"section": "unmapped", "key": f"{r['source_field']}:{r['value']}", "value": int(r["parties"]),
                         "source": "category_map.csv", "note": "-> unknown"})
    for part in ("person", "business"):
        for rep in scored[part][3]["report"]:
            rows.append({"section": "blocking", "key": f"{part}.{rep['rule']}", "value": rep["pairs_after_refine"],
                         "source": "key counts before indexing", "pairs": rep["pairs_before_refine"],
                         "note": (f"oversized keys {rep['oversized_keys']}, dropped {rep['dropped_keys']} "
                                  f"({rep['dropped_pairs']} pairs) {rep['dropped_examples']}").strip()})
        for k, v in scored[part][3]["rule_counts"].items():
            rows.append({"section": "blocking.proposed", "key": f"{part}.{k}", "value": v, "source": "indexing"})
        rows.append({"section": "blocking.proposed", "key": f"{part}.scored_pairs", "value": scored[part][3]["scored"],
                     "source": "indexing"})
    W = pd.concat([params["weights"]["person"], params["weights"]["business"]], ignore_index=True)
    for _, r in W.iterrows():
        k = f"{r['part']}.{r['field']}.{r['level']}"
        rows.append({"section": "m", "key": k, "value": r["m"], "source": r["m_chain"], "pairs": r["m_pairs"],
                     "ci_low": r["m_lo"], "ci_high": r["m_hi"], "note": r["flag"]})
        rows.append({"section": "u", "key": k, "value": r["u"], "source": r["u_source"], "pairs": r["u_pairs"],
                     "note": ("value-specific on this level: " + r["u_value_specific"]) if r["u_value_specific"] else ""})
    for k, v in (params["components"] or {}).items():
        rows.append({"section": "u.name_components", "key": k, "value": v, "source": "random pairs"})
    for s in params["sources"]:
        rows.append({"section": "m.sources", "key": f"{s['part']}.{s['source']}", "value": s["pairs"], "source": "pairs"})
    for part, e in params["em"].items():
        rows.append({"section": "m.em", "key": part, "value": json.dumps(e), "source": "EM, u fixed"})
    for _, r in prior_df.iterrows():
        rows.append({"section": "prior", "key": f"{r['part']}.{r['group']}", "value": r["prior"],
                     "source": f"strict pairs {r['strict_pairs']} / recall {r['recall']:.3f} / all pairs {r['all_pairs']}",
                     "pairs": r["strict_pairs"], "note": r["flag"]})
    for _, r in sens.iterrows():
        rows.append({"section": "sensitivity", "key": f"{r['part']}.{r['group']}.prior_x{r['prior_multiplier']}.recall_x{r['recall_multiplier']}",
                     "value": json.dumps({k: r[k] for k in r.index if k.startswith("entities")}), "source": f"prior {r['prior']:.3g}"})
    for a in diag["anchor_recall"]:
        rows.append({"section": "diagnostics", "key": f"identifier_anchor_recall.{a['part']}", "value": a["recall"],
                     "pairs": a["identifier_anchor_pairs"], "source": "name rules only"})
    for t in diag["truth"]:
        rows.append({"section": "diagnostics", "key": f"truth.{t['part']}", "value": json.dumps(t, default=str),
                     "source": "truth file (diagnostics only)"})
    vet = 0
    for part in ("person", "business"):
        S = scored[part][0]
        if len(S):
            for v, n in S.loc[S["veto"] != "", "veto"].value_counts().items():
                rows.append({"section": "vetoes", "key": f"{part}.{v}", "value": int(n), "source": "score"})
    for r in sw.rows:
        rows.append({"section": "timing", "key": r["step"], "value": r["seconds"], "source": "wall seconds",
                     "note": f"peak {r['peak_rss_gb']} GB"})
    m = pd.DataFrame(rows)
    for c in ("section", "key", "value", "source", "pairs", "ci_low", "ci_high", "note"):
        if c not in m:
            m[c] = ""
    m = m[["section", "key", "value", "source", "pairs", "ci_low", "ci_high", "note"]].fillna("")
    m["value"] = m["value"].map(lambda v: v if isinstance(v, (int, float, np.integer, np.floating)) else str(v))
    return m
