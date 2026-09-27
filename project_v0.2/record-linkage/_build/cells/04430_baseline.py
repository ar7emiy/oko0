BASELINE_LEGAL = {"inc", "llc", "pc", "pllc", "corp", "corporation", "co", "ltd", "llp", "lp", "pa", "company",
                  "incorporated", "plc", "lc"}
BASELINE_TITLES = {"dr", "doctor", "mr", "mrs", "ms", "miss", "prof", "hon", "jr", "sr", "ii", "iii", "iv",
                   "md", "do", "dc", "dpm", "dds", "dmd", "phd", "np", "rn", "esq", "jd", "cpa", "lcsw", "psyd", "dpt"}
BASELINE_ASSUMED = ("threshold 90; cleaning: lowercase, punctuation, legal suffixes, titles; persons first + last; "
                    "missing category blocks: ASSUMED until the user supplies the real settings")


def baseline_clean(name, cfg):
    # _undot first ('M.D.' -> 'MD', so it is recognized as one credential word, not 'm' 'd')
    s = re.sub(r"[^\w\s]", " ", _undot(fold(name)).lower().replace("&", " and "))
    drop = (BASELINE_LEGAL if cfg.baseline_strip_legal else set()) | (BASELINE_TITLES if cfg.baseline_strip_titles else set())
    return " ".join(w for w in s.split() if w not in drop)


def baseline_frame(F, part, cfg, watchlist):
    """Per party: the cleaned entity name and the category the gate reads."""
    if part == "person":
        raw = F["first"] + " " + (F["middle"] + " " if cfg.baseline_include_middle else "") + F["last"]
    else:
        raw = F["business_raw"]
    name = map_unique(raw, lambda s: baseline_clean(s, cfg)).to_numpy(dtype=object)
    cat = (F["category"] if watchlist else F["category_given"]).to_numpy(dtype=object)
    cat = np.where(np.isin(cat, ["", "other"]), "", cat)
    return name, cat


def baseline_scores(xnames, wnames, pairs_l, pairs_r):
    """token_sort_ratio for given pairs."""
    return np.array([_rf_fuzz.token_sort_ratio(xnames[i], wnames[j]) if xnames[i] and wnames[j] else 0.0
                     for i, j in zip(pairs_l, pairs_r)], dtype=float)


def add_baseline_columns(pr, pairs, ents, cfg):
    """p_baseline on every candidate (entity x watchlist) pair: the best token_sort_ratio / 100
    any member row of the entity reaches against the watchlist name, 0 when the category gate
    blocks every such row; baseline_match: that score reaches baseline_threshold."""
    if not len(pairs):
        return pairs.assign(p_baseline=pd.Series(dtype=float), baseline_match=pd.Series(dtype=bool))
    pb = np.zeros(len(pairs))
    for part in ("person", "business"):
        m = (pairs["part"] == part).to_numpy()
        if not m.any():
            continue
        X, W = pr.X[part], pr.W[part]
        ent = ents[part]
        xn, xc = baseline_frame(X, part, cfg, False)
        wn, wc = baseline_frame(W, part, cfg, True)
        e = pairs["_e"].to_numpy()[m].astype(np.int64)
        r = pairs["_r"].to_numpy()[m].astype(np.int64)
        n_e = ent.size[e]
        g = np.repeat(np.arange(len(e)), n_e)
        offs = np.arange(len(g)) - np.repeat(np.cumsum(n_e) - n_e, n_e)
        mem = ent.order[ent.start[e][g] + offs]
        rr = r[g]
        s = baseline_scores(xn, wn, mem, rr)
        gate = (xc[mem] == wc[rr]) & (xc[mem] != "")
        if cfg.baseline_gate_missing == "pass":
            gate |= (xc[mem] == "") | (wc[rr] == "")
        best = pd.Series(np.where(gate, s, 0.0)).groupby(g).max().to_numpy()
        pb[m] = best / 100.0
    out = pairs.copy()
    out["p_baseline"] = pb
    out["baseline_match"] = pb * 100.0 >= cfg.baseline_threshold
    return out


def baseline_table(pr, B, rows):
    """The baseline's matches at the row level, with the B1 entity of the extracted row."""
    if not len(B):
        return pd.DataFrame(columns=["part", "x_party_id", "extracted_record_id", "entity_id", "watchlist_record_id",
                                     "score", "p_baseline", "gate_ok", "x_category", "w_category", "baseline_match"])
    ent = rows.set_index("party_id")["entity_id"]
    wr = pd.concat([pr.W[p][["party_id", "record_id"]] for p in ("person", "business")]).set_index("party_id")["record_id"]
    xr = pd.concat([pr.X[p][["party_id", "record_id"]] for p in ("person", "business")]).set_index("party_id")["record_id"]
    return pd.DataFrame({"part": B["part"], "x_party_id": B["x_party_id"],
                         "extracted_record_id": xr.reindex(B["x_party_id"]).to_numpy(),
                         "entity_id": ent.reindex(B["x_party_id"]).to_numpy(),
                         "watchlist_record_id": wr.reindex(B["w_party_id"]).to_numpy(),
                         "score": B["score"], "p_baseline": np.where(B["gate_ok"], B["score"] / 100.0, 0.0),
                         "gate_ok": B["gate_ok"], "x_category": B["x_category"], "w_category": B["w_category"],
                         "baseline_match": B["match"]})


def run_baseline(pr, cfg, log=print):
    """Every extracted x watchlist party pair (same part) whose cleaned names reach the
    threshold, with whether the category gate lets it through. Returns a frame: part, l, r,
    x_party_id, w_party_id, score, gate_ok, match."""
    from rapidfuzz import process
    t0 = time.time()
    out = []
    for part in ("person", "business"):
        X, W = pr.X[part], pr.W[part]
        if not len(X) or not len(W):
            continue
        xn, xc = baseline_frame(X, part, cfg, False)
        wn, wc = baseline_frame(W, part, cfg, True)
        wi = np.flatnonzero(wn != "")
        xi_all = np.flatnonzero(xn != "")
        step = max(1, 20_000_000 // max(1, len(wi)))
        for lo in range(0, len(xi_all), step):
            xi = xi_all[lo:lo + step]
            M = process.cdist(list(xn[xi]), list(wn[wi]), scorer=_rf_fuzz.token_sort_ratio,
                              score_cutoff=cfg.baseline_threshold, dtype=np.uint8, workers=-1)
            a, b = np.nonzero(M)
            if not len(a):
                continue
            l, r = xi[a], wi[b]
            gate = (xc[l] == wc[r]) & (xc[l] != "")
            if cfg.baseline_gate_missing == "pass":
                gate |= (xc[l] == "") | (wc[r] == "")
            out.append(pd.DataFrame({"part": part, "l": l, "r": r, "x_party_id": X["party_id"].to_numpy()[l],
                                     "w_party_id": W["party_id"].to_numpy()[r], "score": M[a, b].astype(float),
                                     "gate_ok": gate, "x_category": xc[l], "w_category": wc[r]}))
    B = pd.concat(out, ignore_index=True) if out else pd.DataFrame(
        columns=["part", "l", "r", "x_party_id", "w_party_id", "score", "gate_ok", "x_category", "w_category"])
    B["match"] = B["gate_ok"].astype(bool)
    log(f"baseline: {len(B):,} pairs with token_sort_ratio >= {cfg.baseline_threshold:g}, "
        f"{int(B['match'].sum()):,} through the category gate ({time.time() - t0:.0f}s)")
    return B
