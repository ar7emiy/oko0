import dataclasses

HOLDOUT_COLUMNS = {"ssn": ["ssn"], "npi": ["provider_npi"], "tin": ["tin"],
                   "dl": ["driver_license_number", "driver_license_state"]}
HOLDOUT_PART = {"ssn": "person", "npi": "person", "dl": "person", "tin": "business"}
EVAL_BINS = [0.0, 0.1, 0.5, 0.8, 0.9, 0.95, 0.99, 1.0000001]


def b1_row_pairs(run, part, x_scope=None):
    """Every kept (extracted party, watchlist party) pair at the row level: a member row of an
    entity inherits the entity's pairs."""
    P = run["pairs"]
    P = P[P["part"] == part] if len(P) else P
    rows = run["rows"]
    R = rows[rows["part"] == part][["party_id", "entity_id"]].rename(columns={"party_id": "x_party_id"})
    if x_scope is not None:
        R = R[R["x_party_id"].isin(x_scope)]
    if not len(P):
        return pd.DataFrame(columns=["x_party_id", "entity_id", "w_party_id", "p", "basis", "rank", "cluster_status",
                                     "pair_id", "veto"])
    W = run["pr"].W[part]
    Pm = pd.DataFrame({"entity_id": P["entity_id"].to_numpy(), "w_party_id": W["party_id"].to_numpy()[P["_r"].to_numpy()],
                       "p": P["p"].to_numpy(), "basis": P["basis"].to_numpy(), "rank": P["rank"].to_numpy(),
                       "cluster_status": P["cluster_status"].to_numpy(), "pair_id": P["pair_id"].to_numpy(),
                       "veto": P["veto"].to_numpy()})
    return R.merge(Pm, on="entity_id", how="inner")


def proposed_mask(run, part, x_party_ids, w_party_ids):
    """Was each (extracted party, watchlist party) proposed by the candidate stage (as its
    entity's pair)? Parties absent from the run count as not proposed."""
    X, W = run["pr"].X[part], run["pr"].W[part]
    ent = run["scored"]["entities"][part]
    xi = pd.Series(np.arange(len(X)), index=X["party_id"].to_numpy())
    wi = pd.Series(np.arange(len(W)), index=W["party_id"].to_numpy())
    a = xi.reindex(x_party_ids).to_numpy()
    b = wi.reindex(w_party_ids).to_numpy()
    ok = ~np.isnan(a) & ~np.isnan(b)
    out = np.zeros(len(a), dtype=bool)
    if ok.any():
        out[ok] = np.isin(_key(ent.e_of[a[ok].astype(np.int64)], b[ok].astype(np.int64)),
                          run["scored"]["link"][part][3]["keys"])
    return out


def evaluate(method, test, pos, pred, label, thresholds, score_col="p", basis_col="basis", proposed=None):
    """Metrics of one method on one test. `pos`: truth positives (x_party_id, w_party_id).
    `pred`: the method's pairs with a score; `label`: 1 true / 0 false / -1 unknown per row of
    pred. A positive the method did not produce scores 0. Returns (bands, bins, basis, funnel)."""
    pred = pred.assign(_label=label)
    known = pred[pred["_label"] >= 0]
    pk = set(zip(pos["x_party_id"], pos["w_party_id"]))
    score_of = dict(zip(zip(known["x_party_id"], known["w_party_id"]), known[score_col]))
    ps = np.array([score_of.get(k, 0.0) for k in zip(pos["x_party_id"], pos["w_party_id"])], dtype=float)
    neg = known[known["_label"] == 0]
    bands = []
    for t in thresholds:
        tp = int((ps >= t).sum())
        fp = int((neg[score_col] >= t).sum())
        fn = len(ps) - tp
        bands.append({"test": test, "method": method, "threshold": t, "true_pairs": len(ps), "tp": tp, "fp": fp, "fn": fn,
                      "precision": tp / (tp + fp) if tp + fp else np.nan, "recall": tp / len(ps) if len(ps) else np.nan})
    bins = []
    for lo, hi in zip(EVAL_BINS[:-1], EVAL_BINS[1:]):
        bins.append({"test": test, "method": method, "p_from": lo, "p_to": min(1.0, hi),
                     "true_pairs": int(((ps >= lo) & (ps < hi)).sum()),
                     "false_pairs": int(((neg[score_col] >= lo) & (neg[score_col] < hi)).sum())})
    basis = []
    if basis_col in known:
        hit = known[known[score_col] >= 0.5]
        for b, g in hit.groupby(basis_col):
            tp = int((g["_label"] == 1).sum()); fp = int((g["_label"] == 0).sum())
            basis.append({"test": test, "method": method, "basis": b, "tp_at_0.5": tp, "fp_at_0.5": fp,
                          "precision": tp / (tp + fp) if tp + fp else np.nan,
                          "share_of_true_found": tp / len(ps) if len(ps) else np.nan})
    funnel = {"test": test, "method": method, "true_pairs": len(ps),
              "proposed": int(proposed.sum()) if proposed is not None else np.nan,
              "lost_at_candidates": int((~proposed).sum()) if proposed is not None else np.nan,
              "kept": int((ps > 0).sum()), "p_ge_0.5": int((ps >= 0.5).sum()), "p_ge_0.9": int((ps >= 0.9).sum()),
              "known_false_pairs_scored": len(neg)}
    return pd.DataFrame(bands), pd.DataFrame(bins), pd.DataFrame(basis), funnel


def baseline_eval(test, pos, B, label_fn, thresholds, part_names):
    """The baseline on the same truth: a match is a pair through the gate at or above the
    threshold (score 1), everything else 0; lost true pairs split by reason."""
    pred = B[B["match"]].rename(columns={"score": "ts"}).assign(p=1.0, basis="name (baseline)")
    lab = label_fn(pred) if len(pred) else np.array([], dtype=int)
    bands, bins, basis, funnel = evaluate("baseline", test, pos, pred, lab, [0.5], "p", "basis")
    bands["threshold"] = f"token_sort >= {part_names['threshold']:g} + category gate"
    # why each lost true pair was lost
    allb = {(x, w): (s, g) for x, w, s, g in zip(B["x_party_id"], B["w_party_id"], B["score"], B["gate_ok"])}
    reasons = []
    for x, w, part in zip(pos["x_party_id"], pos["w_party_id"], pos["part"]):
        s, g = allb.get((x, w), (None, None))
        if s is not None and g:
            continue
        reasons.append("blocked by category gate" if s is not None else "name too different")
    funnel["lost_blocked_by_category_gate"] = int(sum(r == "blocked by category gate" for r in reasons))
    funnel["lost_name_too_different"] = int(sum(r == "name too different" for r in reasons))
    return bands, bins, basis, funnel


def disagreements(test, pos, b1pred, b1label, B, blabel, evidence, run, cfg, cap=200):
    """Rows where B1 and the baseline disagree, with B1's decision card."""
    pk = set(zip(pos["x_party_id"], pos["w_party_id"]))
    b1p = dict(zip(zip(b1pred["x_party_id"], b1pred["w_party_id"]), b1pred["p"]))
    b1pair = dict(zip(zip(b1pred["x_party_id"], b1pred["w_party_id"]), b1pred["pair_id"]))
    b1basis = dict(zip(zip(b1pred["x_party_id"], b1pred["w_party_id"]), b1pred["basis"]))
    bm = B[B["match"]]
    bset = dict(zip(zip(bm["x_party_id"], bm["w_party_id"]), bm["score"]))
    bneg = set(k for k, l_ in zip(zip(bm["x_party_id"], bm["w_party_id"]), blabel) if l_ == 0)
    rows = []
    for k in sorted(bneg):                                   # baseline false alarms
        p = b1p.get(k, 0.0)
        rows.append(("false alarm B1 avoids" if p < 0.5 else "false alarm in both", k, bset[k], p))
    for k in sorted(pk):
        inb = k in bset
        p = b1p.get(k, 0.0)
        if not inb and p >= 0.5:
            rows.append(("match B1 recovers", k, np.nan, p))
        elif inb and p < 0.5:
            rows.append(("match the baseline finds and B1 misses", k, bset[k], p))
    if not rows:
        return pd.DataFrame(columns=["test", "kind", "x_party_id", "w_party_id", "baseline_score", "b1_p", "b1_basis",
                                     "decision_card"])
    df = pd.DataFrame(rows, columns=["kind", "k", "baseline_score", "b1_p"])
    df["x_party_id"] = [k[0] for k in df["k"]]
    df["w_party_id"] = [k[1] for k in df["k"]]
    df = df.drop(columns="k")
    df = df.groupby("kind", group_keys=False).head(cap).reset_index(drop=True)
    pid = [b1pair.get((x, w), "") for x, w in zip(df["x_party_id"], df["w_party_id"])]
    cards = decision_cards(evidence, [p for p in pid if p])
    df["b1_basis"] = [b1basis.get((x, w), "not a B1 candidate") for x, w in zip(df["x_party_id"], df["w_party_id"])]
    df["decision_card"] = [cards.get(p, "not kept by B1 (below the keep rule or not proposed)") if p else
                           "not kept by B1 (below the keep rule or not proposed)" for p in pid]
    names = pd.concat([run["pr"].X[p][["party_id", "display_name"]] for p in ("person", "business")]).set_index("party_id")["display_name"]
    wnames = pd.concat([run["pr"].W[p][["party_id", "display_name"]] for p in ("person", "business")]).set_index("party_id")["display_name"]
    df.insert(0, "test", test)
    df.insert(4, "extracted_name", names.reindex(df["x_party_id"]).fillna("").to_numpy())
    df.insert(5, "watchlist_name", wnames.reindex(df["w_party_id"]).fillna("").to_numpy())
    return df


def ambiguity(test, B):
    """How many watchlist rows each extracted name hits under the baseline."""
    bm = B[B["match"]]
    if not len(bm):
        return pd.DataFrame(columns=["test", "watchlist_rows_per_name", "extracted_parties"])
    per = bm.groupby("x_party_id").size()
    band = pd.cut(per, [0, 1, 2, 5, 10, 50, np.inf], labels=["1", "2", "3-5", "6-10", "11-50", ">50"])
    t = band.value_counts().sort_index().rename("extracted_parties").reset_index()
    t.columns = ["watchlist_rows_per_name", "extracted_parties"]
    t.insert(0, "test", test)
    return t


# ---- the held-out identifier check ---------------------------------------------------------
def holdout_truth(pr, t, cfg):
    """Truth for identifier t from the unaltered run: positives (equal values held under at
    most holdout_max_holders holders) and the value of every party that carries t."""
    part = HOLDOUT_PART[t]
    X, W = pr.X[part], pr.W[part]
    col = f"id_{t}"
    vi = pr.vi[pr.vi["type"] == t]
    ok = set(vi.loc[vi["distinct_names"] <= cfg.holdout_max_holders, "value"])
    xv = pd.Series(X[col].to_numpy(dtype=object), index=X["party_id"].to_numpy())
    wv = pd.Series(W[col].to_numpy(dtype=object), index=W["party_id"].to_numpy())
    xv, wv = xv[xv != ""], wv[wv != ""]
    a = pd.DataFrame({"x_party_id": xv.index, "v": xv.to_numpy()})
    b = pd.DataFrame({"w_party_id": wv.index, "v": wv.to_numpy()})
    pos = a[a["v"].isin(ok)].merge(b, on="v")[["x_party_id", "w_party_id"]]
    pos["part"] = part
    return pos, xv.to_dict(), wv.to_dict(), ok


def holdout_label(xval, wval, ok, t):
    num = (lambda v: v.partition(":")[2]) if t == "dl" else (lambda v: v)

    def lab(df):
        out = np.full(len(df), -1, dtype=int)
        for i, (x, w) in enumerate(zip(df["x_party_id"], df["w_party_id"])):
            a, b = xval.get(x), wval.get(w)
            if not a or not b:
                continue
            if a == b:
                out[i] = 1 if a in ok else -1
            elif not _near(num(a), num(b)):
                out[i] = 0
        return out
    return lab


def hide_identifier(df, ids):
    d = df.copy()
    for t in ids:
        for c in HOLDOUT_COLUMNS[t]:
            d[c] = ""
    return d


def _sub_config(cfg):
    return dataclasses.replace(cfg, self_check=False, core=dataclasses.replace(cfg.core))


def run_self_checks(xdf, wdf, maps, ref, cfg, main_run, log=print, sw=None):
    """Held-out identifier check and noise-injection test, B1 and (switch on) the baseline."""
    mark = sw.mark if sw is not None else (lambda s: None)
    res = {"bands": [], "bins": [], "basis": [], "funnel": [], "disagreements": [], "ambiguity": [], "manifest_rows": []}
    sub = _sub_config(cfg)
    thresholds = list(cfg.p_bands)
    pr0 = main_run["pr"]
    truths = {}
    for t in cfg.holdout_ids:
        pos, xv, wv, ok = holdout_truth(pr0, t, cfg)
        if len(pos) >= cfg.holdout_min_pairs:
            truths[t] = (pos, xv, wv, ok)
        else:
            res["manifest_rows"].append({"section": "selfcheck.holdout", "key": f"{t}.not_run", "value": len(pos),
                                         "source": "held-out identifier check",
                                         "note": f"fewer than {cfg.holdout_min_pairs} true pairs carry this identifier on both sides"})
    runs = {}
    if cfg.holdout_mode == "all" and truths:
        r = run_pipeline(hide_identifier(xdf, list(truths)), hide_identifier(wdf, list(truths)), maps, ref, sub)
        runs = {t: r for t in truths}
    else:
        for t in truths:
            log(f"held-out identifier check: {t} hidden, full B1 run")
            runs[t] = run_pipeline(hide_identifier(xdf, [t]), hide_identifier(wdf, [t]), maps, ref, sub)
    B0 = (main_run["baseline_raw"] if "baseline_raw" in main_run else run_baseline(pr0, cfg, log)) if cfg.baseline else None
    for t, (pos, xv, wv, ok) in truths.items():
        part = HOLDOUT_PART[t]
        test = f"holdout:{t}"
        run = runs[t]
        pred = b1_row_pairs(run, part, set(xv))
        lab = holdout_label(xv, wv, ok, t)
        prop = proposed_mask(run, part, pos["x_party_id"].to_numpy(), pos["w_party_id"].to_numpy())
        bd, bn, bs, fn = evaluate("B1", test, pos, pred, lab(pred), thresholds, proposed=prop)
        for k, v in (("bands", bd), ("bins", bn), ("basis", bs)):
            res[k].append(v)
        res["funnel"].append(fn)
        if B0 is not None:
            Bp = B0[(B0["part"] == part) & B0["x_party_id"].isin(set(xv))]
            bd2, bn2, bs2, fn2 = baseline_eval(test, pos, Bp, lab, thresholds, {"threshold": cfg.baseline_threshold})
            for k, v in (("bands", bd2), ("bins", bn2), ("basis", bs2)):
                res[k].append(v)
            res["funnel"].append(fn2)
            Bm = Bp[Bp["match"]]
            res["disagreements"].append(disagreements(test, pos, pred, lab(pred), Bp, lab(Bm), run["evidence"], run, cfg))
            res["ambiguity"].append(ambiguity(test, Bp))
    mark("16b held-out identifier check")
    # ---- noise-injection test ----
    Xn, truth_n = noise_test_inputs(wdf, maps, ref, cfg)
    log(f"noise-injection test: {len(Xn):,} extracted rows ({int(truth_n['x_record_id'].nunique()):,} noisy copies), full B1 run")
    Xn, _ = validate_input(Xn, "noise test")
    run_n = run_pipeline(Xn, wdf, maps, ref, sub)
    pos_n, lab_n, scope = noise_truth(run_n, truth_n)
    for part in ("person", "business"):
        pp = pos_n[pos_n["part"] == part]
        if not len(pp):
            continue
        test = f"noise:{part}"
        pred = b1_row_pairs(run_n, part, scope[part])
        prop = proposed_mask(run_n, part, pp["x_party_id"].to_numpy(), pp["w_party_id"].to_numpy())
        bd, bn, bs, fn = evaluate("B1", test, pp, pred, lab_n(pred), thresholds, proposed=prop)
        for k, v in (("bands", bd), ("bins", bn), ("basis", bs)):
            res[k].append(v)
        res["funnel"].append(fn)
        if cfg.baseline:
            Bn = run_baseline(run_n["pr"], cfg, log)
            Bp = Bn[(Bn["part"] == part) & Bn["x_party_id"].isin(scope[part])]
            bd2, bn2, bs2, fn2 = baseline_eval(test, pp, Bp, lab_n, thresholds, {"threshold": cfg.baseline_threshold})
            for k, v in (("bands", bd2), ("bins", bn2), ("basis", bs2)):
                res[k].append(v)
            res["funnel"].append(fn2)
            res["disagreements"].append(disagreements(test, pp, pred, lab_n(pred), Bp, lab_n(Bp[Bp["match"]]),
                                                      run_n["evidence"], run_n, cfg))
            res["ambiguity"].append(ambiguity(test, Bp))
    mark("16b noise-injection test")
    out = {k: (pd.concat(v, ignore_index=True) if v and k not in ("funnel", "manifest_rows") else v)
           for k, v in res.items()}
    out["funnel"] = pd.DataFrame(res["funnel"])
    for k in ("bands", "bins", "basis", "disagreements", "ambiguity"):
        if not isinstance(out[k], pd.DataFrame):
            out[k] = pd.DataFrame()
    for f in res["funnel"]:
        for k in ("true_pairs", "lost_at_candidates", "proposed", "kept", "p_ge_0.5", "p_ge_0.9",
                  "lost_blocked_by_category_gate", "lost_name_too_different"):
            if k in f and not (isinstance(f[k], float) and np.isnan(f[k])):
                out["manifest_rows"].append({"section": "selfcheck.funnel", "key": f"{f['test']}.{f['method']}.{k}",
                                             "value": f[k], "source": "self-check (truth: held-out identifier or noise copy)",
                                             "note": "true pairs the candidate stage lost" if k == "lost_at_candidates" else ""})
    if len(out["bands"]):
        for _, r in out["bands"].iterrows():
            out["manifest_rows"].append({"section": "selfcheck.metrics", "key": f"{r['test']}.{r['method']}.{r['threshold']}",
                                         "value": json.dumps({"precision": r["precision"], "recall": r["recall"], "tp": r["tp"],
                                                              "fp": r["fp"], "fn": r["fn"], "true_pairs": r["true_pairs"]}),
                                         "source": "self-check"})
    if cfg.baseline:
        out["manifest_rows"].append({"section": "selfcheck.baseline", "key": "settings", "value": BASELINE_ASSUMED,
                                     "source": "RunConfig.baseline_*"})
    log("self-check metrics:\n" + (out["bands"].to_string(index=False, float_format=lambda v: f"{v:.4f}") if len(out["bands"]) else "none"))
    log("self-check funnel:\n" + out["funnel"].to_string(index=False))
    return out


# ---- the noise-injection test ------------------------------------------------------------
def watchlist_duplicate_groups(W, stats):
    """Watchlist parties of one part joined by a shared valid SSN, NPI, DL, TIN or clinic
    NPI: group id per party."""
    n = len(W)
    a, b = [], []
    for c in ("id_ssn", "id_npi", "id_dl", "id_tin", "id_cnpi"):
        if c not in W:
            continue
        d = pd.DataFrame({"pos": np.arange(n), "v": W[c].to_numpy(dtype=object)})
        d = d[d["v"] != ""]
        first = d.groupby("v")["pos"].transform("min")
        m = d["pos"] != first
        a.append(first[m].to_numpy()); b.append(d["pos"][m].to_numpy())
    a = np.concatenate(a) if a else np.array([], np.int64)
    b = np.concatenate(b) if b else np.array([], np.int64)
    cid, _, _ = constrained_clusters(n, a, b, np.ones(len(a)), {}, fields=[])
    return cid


def noise_test_inputs(wdf, maps, ref, cfg):
    """Noisy copies of watchlist rows (1..noise_max_copies each) and fictional decoys, with
    the truth of the copies (x_record_id, part, w_record_id)."""
    rng = np.random.default_rng(cfg.seed + 101)
    has_party = (wdf["first_name"] != "") | (wdf["last_name"] != "") | (wdf["business_name"] != "") | \
        (wdf["tin"] != "") | (wdf["clinic_npi"] != "")
    cand = np.flatnonzero(has_party.to_numpy())
    pick = np.sort(rng.choice(cand, size=min(cfg.noise_sources, len(cand)), replace=False)) if len(cand) else np.array([], int)
    src = wdf.iloc[pick][SCHEMA].reset_index(drop=True)
    cm = maps["category_map"]
    spec = dict(zip(cm.loc[cm["source_field"] == "specialty", "value"].map(fold), cm.loc[cm["source_field"] == "specialty", "category"]))
    lic = dict(zip(cm.loc[cm["source_field"] == "license_type", "value"].map(fold), cm.loc[cm["source_field"] == "license_type", "category"]))
    src["category"] = [spec.get(fold(s), "") or lic.get(fold(l), "") for s, l in zip(src["provider_specialty"], src["professional_license_type"])]
    k = rng.integers(1, cfg.noise_max_copies + 1, len(src))
    rep = src.loc[src.index.repeat(k)].reset_index(drop=True)
    j = rep.groupby("record_id").cumcount()
    source_rid = rep["record_id"].to_numpy().copy()
    rep["record_id"] = rep["record_id"] + "#" + j.astype(str)
    fake = Fake(ref, rng)
    copies, _ = apply_noise(rep, maps["simulation_noise"], fake, rng, scale=1.0, id_prefix="nt")
    fict = pd.DataFrame(columns=SCHEMA)
    if cfg.noise_decoys:
        fict, _, _, _, _ = make_dataset(cfg.noise_decoys, max(1, cfg.noise_decoys // 5), 0, ref, maps["simulation_noise"],
                                        cfg.seed + 102, x_share=1.0, w_share=0.0, include_edges=False, prefix="ND")
        fict = fict.iloc[:cfg.noise_decoys]
    X = pd.concat([copies, fict], ignore_index=True)
    order = rng.permutation(len(X))
    X["claim_id"] = [f"NC{i // 3:06d}" for i in np.argsort(order)]
    X["note_id"] = X["claim_id"] + "-N0"
    truth = []
    person = ((rep["first_name"] != "") | (rep["last_name"] != "")).to_numpy()
    business = ((rep["business_name"] != "") | (rep["tin"] != "") | (rep["clinic_npi"] != "")).to_numpy()
    for xr, wr, pp, bb in zip(copies["record_id"], source_rid, person, business):
        if pp:
            truth.append((xr, "person", wr))
        if bb:
            truth.append((xr, "business", wr))
    return X.fillna("").astype(str), pd.DataFrame(truth, columns=["x_record_id", "part", "w_record_id"])


def noise_truth(run, truth):
    """Positives (a copy and its source, plus the source's watchlist duplicates), the label
    function, and the extracted parties in scope (copies and decoys: all of them)."""
    pos, scope, true_sets = [], {}, {}
    for part in ("person", "business"):
        X, W = run["pr"].X[part], run["pr"].W[part]
        grp = watchlist_duplicate_groups(W, run["pr"].ctx.stats)
        wpos = pd.Series(np.arange(len(W)), index=W["record_id"].to_numpy())
        members = pd.Series(W["party_id"].to_numpy()).groupby(grp).agg(list)
        xp = pd.Series(X["party_id"].to_numpy(), index=X["record_id"].to_numpy())
        t = truth[(truth["part"] == part) & truth["x_record_id"].isin(xp.index) & truth["w_record_id"].isin(wpos.index)]
        for xr, wr in zip(t["x_record_id"], t["w_record_id"]):
            xid = xp[xr]
            ws = members[grp[wpos[wr]]]
            true_sets[xid] = set(ws)
            for w in ws:
                pos.append((xid, w, part))
        scope[part] = set(X["party_id"])
    pos = pd.DataFrame(pos, columns=["x_party_id", "w_party_id", "part"]).drop_duplicates()

    def lab(df):
        return np.array([1 if w in true_sets.get(x, ()) else 0 for x, w in zip(df["x_party_id"], df["w_party_id"])],
                        dtype=int)
    return pos, lab, scope
