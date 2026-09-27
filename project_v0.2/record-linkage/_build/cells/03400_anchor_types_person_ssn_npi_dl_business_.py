ANCHOR_TYPES = {"person": ["ssn", "npi", "dl"], "business": ["tin"]}
NAME_FREE = {"person": ["name", "middle"], "business": ["org"]}
WDUP_TYPES = {"person": ["ssn", "npi"], "business": ["tin", "cnpi"]}
# Splink-style training passes: each selects pairs by one rule and learns m for every field
# except the ones the rule used (their agreement is forced by the selection).
TRAIN_RULES = {
    "person": [("dob", ["dob"]), ("nysiis_initial", ["name", "middle"]), ("street", ["address"]),
               ("ssn", ["ssn"]), ("npi", ["npi"]), ("phone", ["phone"]), ("email", ["email"])],
    "business": [("rare_word", ["org"]), ("street", ["address"]), ("tin", ["tin"]), ("cnpi", ["cnpi"]),
                 ("phone", ["phone"])],
}


@dataclass
class Model:
    """The trained parameters of one comparison setting: 'link' (extracted x watchlist) or
    'dedup' (extracted x extracted)."""
    kind: str
    weights: dict        # part -> weights table (one row per field and level)
    prior: dict          # (part, group) -> prior probability that a random pair matches
    prior_df: pd.DataFrame
    passes: dict         # part -> list of training-pass summaries
    u_sample_pairs: dict  # part -> random pairs behind the fuzzy levels of u


def _pairs_within(groups, cap, rng, exclude_same=None):
    """All pairs within each group of positions (at most cap per group, deterministic)."""
    ls, rs = [], []
    for g in groups:
        g = np.asarray(g)
        i, j = np.triu_indices(len(g), k=1)
        a, b = g[i], g[j]
        if exclude_same is not None:
            keep = exclude_same[a] != exclude_same[b]
            a, b = a[keep], b[keep]
        if len(a) > cap:
            sel = np.sort(rng.choice(len(a), cap, replace=False))
            a, b = a[sel], b[sel]
        ls.append(a); rs.append(b)
    if not ls:
        return np.array([], np.int64), np.array([], np.int64)
    return np.concatenate(ls).astype(np.int64), np.concatenate(rs).astype(np.int64)


def anchor_pairs(fr, types, holders, name_condition, cap, rng, exclude_notes=True):
    """Pairs of parties within one frame sharing a value of `types`. name_condition=True keeps
    values held under exactly one name (strict); holders=(lo, hi) bounds the parties per value.
    Returns (l, r, anchor-field mask dict)."""
    notes = fr["note_id"].to_numpy(dtype=object) if exclude_notes else None
    if notes is not None:
        notes = np.where(notes == "", "row:" + fr["record_id"].to_numpy(dtype=object), notes)
    found = []
    for t in types:
        col = f"id_{t}"
        v = fr[col].to_numpy(dtype=object)
        d = pd.DataFrame({"pos": np.arange(len(fr)), "v": v, "n": fr["holder_key"].to_numpy(dtype=object)})
        d = d[d["v"] != ""]
        if not len(d):
            continue
        g = d.groupby("v")
        size = g["pos"].size()
        names = g["n"].nunique()
        ok = (size >= holders[0]) & (size <= holders[1])
        if name_condition:
            ok &= names == 1
        keep = set(size.index[ok])
        grp = [x["pos"].to_numpy() for v, x in d[d["v"].isin(keep)].groupby("v", sort=True)]
        l, r = _pairs_within(grp, cap, rng, notes)
        found.append(pd.DataFrame({"l": l, "r": r, "t": t}))
    if not found:
        return np.array([], np.int64), np.array([], np.int64), {}
    f = pd.concat(found, ignore_index=True)
    piv = f.assign(one=True).pivot_table(index=["l", "r"], columns="t", values="one", aggfunc="any",
                                         fill_value=False)
    l = piv.index.get_level_values(0).to_numpy()
    r = piv.index.get_level_values(1).to_numpy()
    return l, r, {t: piv[t].to_numpy(dtype=bool) for t in piv.columns}


def name_dob_pairs(fr, cap, rng):
    d = pd.DataFrame({"pos": np.arange(len(fr)), "k": fr["name_key"].to_numpy(dtype=object) + "|" +
                      fr["dob"].to_numpy(dtype=object)})
    d = d[(fr["dob"].to_numpy() != "") & (fr["first"].to_numpy() != "")]
    size = d.groupby("k")["pos"].size()
    keep = set(size.index[(size >= 2) & (size <= 20)])
    grp = [x["pos"].to_numpy() for _, x in d[d["k"].isin(keep)].groupby("k", sort=True)]
    return _pairs_within(grp, cap, rng)


def with_coparty(levels, left, right, part):
    if part == "person":
        levels["co_party"] = coparty_proxy_levels(left, right, levels["l"].to_numpy(), levels["r"].to_numpy())
    return levels


def compare_chunked(L, R, l, r, part, ctx, step=250_000):
    if not len(l):
        return with_coparty(compare_pairs(L, R, l, r, part, ctx), L, R, part)
    parts = [compare_pairs(L, R, l[lo:lo + step], r[lo:lo + step], part, ctx) for lo in range(0, len(l), step)]
    return with_coparty(pd.concat(parts, ignore_index=True), L, R, part)


# ---- u ---------------------------------------------------------------------------------------
def random_pairs(nl, nr, n, seed, same_frame):
    """n random pairs (with replacement) of positions; distinct parties within one frame."""
    rng = np.random.default_rng(seed)
    if same_frame:
        l = rng.integers(0, nl, n)
        r = rng.integers(0, nl - 1, n)
        r = np.where(r >= l, r + 1, r)
        return l.astype(np.int64), r.astype(np.int64)
    idx = rl.Index()
    idx.add(rl.index.Random(n, replace=True, random_state=seed))
    mi = idx.index(pd.DataFrame(index=np.arange(nl)), pd.DataFrame(index=np.arange(nr)))
    return mi.get_level_values(0).to_numpy().astype(np.int64), mi.get_level_values(1).to_numpy().astype(np.int64)


def estimate_u_model(L, R, part, ctx, n, seed, same_frame, log=print, label=""):
    """u for one part: exact levels in closed form over all pairs, the rest from n random
    pairs. Returns (u table, random-pair levels, sample size)."""
    t0 = time.time()
    nl, nr = len(L), len(L if same_frame else R)
    total = nl * (nl - 1) // 2 if same_frame else nl * nr
    n = int(min(n, total))
    if n <= 0:
        u_s = estimate_u(pd.DataFrame(), PART_FIELDS[part], ctx.params)
        return u_s, pd.DataFrame(), 0
    l, r = random_pairs(nl, nr, n, seed, same_frame)
    lv = compare_chunked(L, L if same_frame else R, l, r, part, ctx)
    u_s = estimate_u(lv, PART_FIELDS[part], ctx.params)
    closed = closed_form_u(L, R, part, ctx.stats.single.get("phone", set()), same_frame)
    u_df = pd.concat([combine_u(u_s, closed, f, ctx.params) for f in PART_FIELDS[part]], ignore_index=True)
    log(f"u[{label}{part}]: {len(lv):,} random pairs for the fuzzy levels, "
        f"{sum(len(v) for v in closed.values())} levels in closed form ({time.time() - t0:.0f}s)")
    return u_df, lv, n


# ---- the prior centre of m: the build's source chain ------------------------------------------
def prior_centre_m(pr, maps, ref, cfg, wdf, u_link, rng, log=print):
    """m per field from anchors, watchlist duplicates, simulation and published values, shrunk
    in a chain (combine_m). It is the centre of the Dirichlet prior the training passes use,
    so thin data shrinks toward it. Returns ({part: rows}, sources, loose-anchor EM summary)."""
    p = cfg.core
    ctx = pr.ctx
    pub = maps["published_m"]
    pub_arr = lambda f: np.array([float(pub[(pub["field"] == f) & (pub["level"] == lev)]["m"].iloc[0])
                                  for lev in FIELD_LEVELS[f]])
    sources, em_info, centre = [], {}, {}
    t0 = time.time()
    # simulation: noisy copies of watchlist rows
    k = min(cfg.sim_records, len(wdf))
    pick = np.sort(rng.choice(len(wdf), size=k, replace=False)) if k else np.array([], int)
    src = wdf.iloc[pick][SCHEMA].reset_index(drop=True)
    fake = Fake(ref, rng)
    copies, _ = apply_noise(src, maps["simulation_noise"], fake, rng, scale=1.0, id_prefix="sim")
    _, cpar, _, _, _, _ = rows_to_parties(copies, "S", maps, ctx.nick, p, False)
    C = split_parts(cpar)
    sim_counts = {}
    for part in ("person", "business"):
        Cf, W = C[part], pr.W[part]
        wpos = pd.Series(np.arange(len(W)), index=W["record_id"].to_numpy())
        orig = Cf["record_id"].str.replace("sim:", "", regex=False)
        ok = orig.isin(wpos.index).to_numpy()
        l = np.flatnonzero(ok)
        r = wpos[orig[ok]].to_numpy() if ok.any() else np.array([], np.int64)
        lv = compare_chunked(Cf, W, l, r, part, ctx)
        sim_counts[part] = level_counts(lv, PART_FIELDS[part])
        sources.append({"part": part, "source": "simulation", "pairs": len(lv)})
    log(f"prior centre: simulation, {k:,} noisy copies compared ({time.time() - t0:.0f}s)")
    for part in ("person", "business"):
        X, W = pr.X[part], pr.W[part]
        fields = PART_FIELDS[part]
        non_name = [f for f in fields if f not in NAME_FREE[part]]
        l, r, amask = anchor_pairs(X, ANCHOR_TYPES[part], (2, 10 ** 9), True, cfg.anchor_pairs_per_value, rng)
        lv1 = compare_chunked(X, X, l, r, part, ctx)
        c1a = level_counts(lv1, non_name, exclude=amask)
        sources.append({"part": part, "source": "anchors_strict", "pairs": len(lv1)})
        l, r, dmask = anchor_pairs(W, WDUP_TYPES[part], (2, 20), False, cfg.anchor_pairs_per_value, rng,
                                   exclude_notes=False)
        lv2 = compare_chunked(W, W, l, r, part, ctx)
        c2 = level_counts(lv2, fields, exclude=dmask)
        n_wdup = len(lv2)
        if part == "person":
            l, r = name_dob_pairs(W, cfg.anchor_pairs_per_value, rng)
            lv2b = compare_chunked(W, W, l, r, part, ctx)
            c2b = level_counts(lv2b, [f for f in fields if f not in ("name", "dob")])
            for f, (cnt, n) in c2b.items():
                c0, n0 = c2.get(f, (np.zeros(len(FIELD_LEVELS[f])), 0.0))
                c2[f] = (c0 + cnt, n0 + n)
            n_wdup += len(lv2b)
        sources.append({"part": part, "source": "watchlist_duplicates", "pairs": n_wdup})
        rows = []
        z = lambda f: np.zeros(len(FIELD_LEVELS[f]))
        for f in non_name:
            srcs = [("anchors_strict", *c1a.get(f, (z(f), 0.0))), ("watchlist_duplicates", *c2.get(f, (z(f), 0.0))),
                    ("simulation", *sim_counts[part].get(f, (z(f), 0.0)))]
            rows += combine_m(f, srcs, pub_arr(f), p)
        mfix = pd.DataFrame(rows)
        u_df = u_link[part]
        l, r, lmask = anchor_pairs(X, ANCHOR_TYPES[part], cfg.loose_holders, False, cfg.anchor_pairs_per_value, rng)
        lv1b = compare_chunked(X, X, l, r, part, ctx)
        fixed = [f for f in non_name if f != "co_party"]
        m_fixed = {f: mfix[mfix["field"] == f].sort_values("level_code")["m"].to_numpy() for f in fixed}
        u_tab = {f: u_df[u_df["field"] == f].sort_values("level_code")["u"].to_numpy() for f in fields if f != "co_party"}
        em, lam, iters = em_fixed_u(lv1b, NAME_FREE[part], fixed, m_fixed, u_tab, p, exclude=lmask)
        em_info[part] = {"pairs": len(lv1b), "lambda": lam, "iterations": iters}
        sources.append({"part": part, "source": "anchors_loose_em", "pairs": len(lv1b)})
        for f in NAME_FREE[part]:
            cnt, n = (em[f][2], em[f][1]) if f in em else (z(f), 0.0)
            srcs = [("anchors_loose_em", cnt, n), ("watchlist_duplicates", *c2.get(f, (z(f), 0.0))),
                    ("simulation", *sim_counts[part].get(f, (z(f), 0.0)))]
            rows += combine_m(f, srcs, pub_arr(f), p)
        centre[part] = pd.DataFrame(rows)
        log(f"prior centre [{part}]: strict anchors {len(lv1):,}, loose anchors {len(lv1b):,} "
            f"(EM lambda {lam:.3f}), watchlist duplicates {n_wdup:,} ({time.time() - t0:.0f}s)")
    return centre, sources, em_info


# ---- training passes ---------------------------------------------------------------------------
def training_pairs(L, R, part, rule, ctx, cfg, rng, same_frame):
    """Pairs sharing a key of `rule` (at most about em_key_cap per key: each side of an
    oversized key is sampled), at most em_pairs_per_pass in all."""
    xk = rule_keys(L, part, rule, ctx.rarity, "x", ctx.dba_pairs)
    wk = rule_keys(L if same_frame else R, part, rule, ctx.rarity, "w", ctx.dba_pairs)
    side = max(2, int(math.sqrt(cfg.em_key_cap)))

    def cap(f):
        if not len(f):
            return f
        f = f.assign(_o=rng.random(len(f))).sort_values(["key", "_o"], kind="stable")
        return f[f.groupby("key").cumcount() < side]
    m = cap(xk)[["pos", "key"]].merge(cap(wk)[["pos", "key"]], on="key", suffixes=("_x", "_w"))
    if same_frame:
        m = m[m["pos_x"] != m["pos_w"]]
        a, b = np.minimum(m["pos_x"], m["pos_w"]), np.maximum(m["pos_x"], m["pos_w"])
        m = pd.DataFrame({"pos_x": a, "pos_w": b})
    m = m.drop_duplicates(["pos_x", "pos_w"])
    if len(m) > cfg.em_pairs_per_pass:
        m = m.iloc[np.sort(rng.choice(len(m), cfg.em_pairs_per_pass, replace=False))]
    return m["pos_x"].to_numpy(np.int64), m["pos_w"].to_numpy(np.int64)


def run_training(L, R, part, ctx, u_df, m0_rows, cfg, rng, same_frame, label, log=print):
    """Every training pass of one part: EM with u fixed over the fields its rule did not use,
    Dirichlet prior toward the prior centre, bootstrap replicates."""
    t0 = time.time()
    fields_all = [f for f in PART_FIELDS[part] if f != "co_party"]
    u_tab = {f: u_df[u_df["field"] == f].sort_values("level_code")["u"].to_numpy() for f in fields_all}
    m0 = {f: floor_m(m0_rows[m0_rows["field"] == f].sort_values("level_code")["m"].to_numpy(), cfg.core)
          for f in fields_all}
    passes = []
    for rule, excluded in TRAIN_RULES[part]:
        l, r = training_pairs(L, R, part, rule, ctx, cfg, rng, same_frame)
        if len(l) < 20:
            passes.append({"pass": f"{label}:{rule}", "pairs": int(len(l)), "skipped": "fewer than 20 pairs",
                           "m": {}, "boot": [], "converged": False, "lambda": float("nan"), "iterations": 0,
                           "fields": [], "n_match": {}, "excluded": excluded})
            continue
        lv = compare_chunked(L, L if same_frame else R, l, r, part, ctx)
        fields = [f for f in fields_all if f not in excluded]
        est = training_pass_em(lv, fields, u_tab, m0, cfg.core, f"{label}:{rule}", rng, cfg.bootstrap_reps)
        est["excluded"] = excluded
        passes.append(est)
    done = [p_ for p_ in passes if p_["pairs"] and not p_.get("skipped")]
    log(f"EM [{label}{part}]: {len(done)} training passes "
        + ", ".join(f"{p_['pass'].split(':')[-1]} {p_['pairs']:,} pairs lambda {p_['lambda']:.3g}" for p_ in done)
        + f" ({time.time() - t0:.0f}s, {cfg.bootstrap_reps} bootstrap replicates each)")
    return passes


def final_weights(part, passes, m0_rows, u_df, components, params):
    """Weights table of one part: m from the training passes (mean of the passes that saw the
    field, each with the Dirichlet prior), floored; the prior centre where no pass saw the
    field; bootstrap intervals; flags for unstable weights."""
    rows = []
    for f in PART_FIELDS[part]:
        c = m0_rows[m0_rows["field"] == f].sort_values("level_code")
        m0 = c["m"].to_numpy()
        u = u_df[u_df["field"] == f].sort_values("level_code")["u"].to_numpy()
        k = len(FIELD_LEVELS[f])
        if f == "co_party":
            m, lo, hi, per, blo, bhi, flags, spread = m0, c["m_lo"].to_numpy(), c["m_hi"].to_numpy(), {}, \
                np.full(k, np.nan), np.full(k, np.nan), [], np.zeros(k)
            note = "not trained by EM (a proxy level in estimation): prior centre"
            source = "prior centre: " + c["m_chain"].iloc[0]
        else:
            m, lo, hi, per, blo, bhi, flags, spread = combine_passes(passes, f, m0, u, params)
            note = "; ".join(flags)
            source = (f"EM, u fixed: mean of {len(per)} training passes ({', '.join(x.split(':')[-1] for x in per)}), "
                      f"Dirichlet prior ({params.em_prior_strength:g} pseudo-pairs) toward the prior centre"
                      if per else "prior centre only (no training pass saw this field)")
        mf = floor_m(m, params)
        n_match = sum(p_.get("n_match", {}).get(f, 0.0) for p_ in passes if f in p_.get("m", {}))
        for i, lev in enumerate(FIELD_LEVELS[f]):
            relevant = max(mf[i], u[i] if i < len(u) else 0) >= 0.01
            why = []
            if relevant and np.isfinite(bhi[i]) and (bhi[i] - blo[i]) > params.unstable_ci_bits:
                why.append(f"bootstrap 95% interval {bhi[i] - blo[i]:.1f} bits wide")
            if relevant and spread[i] > params.unstable_pass_bits:
                why.append(f"training passes disagree by {spread[i]:.1f} bits")
            rows.append({"field": f, "level": lev, "level_code": i, "m": float(mf[i]),
                         "m_lo": float(lo[i]) if np.isfinite(lo[i]) else np.nan,
                         "m_hi": float(hi[i]) if np.isfinite(hi[i]) else np.nan,
                         "m_source": source, "m_chain": c["m_chain"].iloc[0], "m_pairs": float(n_match),
                         "m_prior_centre": float(m0[i]), "m_published": float(c["m_published"].iloc[i]),
                         "m_passes": json.dumps({kk.split(":")[-1]: round(float(v[i]), 6) for kk, v in per.items()}),
                         "bits_lo": float(blo[i]) if np.isfinite(blo[i]) else np.nan,
                         "bits_hi": float(bhi[i]) if np.isfinite(bhi[i]) else np.nan,
                         "unstable": "; ".join(why), "m_note": note})
    return weights_table(rows, u_df, components, params)


# ---- prior -------------------------------------------------------------------------------------
def strict_pairs(X, W, part, ctx, same_frame=False):
    """Pairs firing a strict rule (not vetoed), as (l, r); within one frame l < r."""
    found = []
    R = X if same_frame else W

    def join(kx, kw):
        a = pd.DataFrame({"k": kx, "l": np.arange(len(X))})
        b = pd.DataFrame({"k": kw, "r": np.arange(len(R))})
        a, b = a[a["k"] != ""], b[b["k"] != ""]
        m = a.merge(b, on="k")
        if same_frame:
            m = m[m["l"] < m["r"]]
        found.append(m[["l", "r"]])

    single = ctx.stats.single
    ids = ["ssn", "npi", "dl", "license", "email", "vin", "plate"] if part == "person" else ["tin", "cnpi", "email"]
    for t in ids:
        kx = X[f"id_{t}"].to_numpy(dtype=object)
        kx = np.where(pd.Series(kx).isin(single.get(t, set())).to_numpy(), kx, "")
        join(kx, R[f"id_{t}"].to_numpy(dtype=object))
    nk = lambda F: np.where((F["first"] != "") | (F["part"] == "business"), F["name_key"], "").astype(object)
    if part == "person":
        join(np.where(X["dob"] != "", nk(X) + "|" + X["dob"], ""), np.where(R["dob"] != "", nk(R) + "|" + R["dob"], ""))
    else:
        join(np.where(X["zip"] != "", nk(X) + "|" + X["zip"], ""), np.where(R["zip"] != "", nk(R) + "|" + R["zip"], ""))
    join(np.where(X["addr_street"] != "", nk(X) + "|" + X["addr_street"], ""),
         np.where(R["addr_street"] != "", nk(R) + "|" + R["addr_street"], ""))
    f = pd.concat(found, ignore_index=True).drop_duplicates()
    if not len(f):
        return f["l"].to_numpy(), f["r"].to_numpy()
    lv = compare_pairs(X, R, f["l"].to_numpy(), f["r"].to_numpy(), part, ctx)
    veto = np.zeros(len(lv), bool)
    for t in VETO_FIELDS:
        if f"veto_{t}" in lv:
            veto |= lv[f"veto_{t}"].to_numpy(dtype=bool)
    return f["l"].to_numpy()[~veto], f["r"].to_numpy()[~veto]


def fill_rates(Xg, W, part):
    sh = lambda F, c: float((F[c] != "").mean()) if len(F) else 0.0
    both = lambda c: sh(Xg, c) * sh(W, c)
    fill = {t: both(f"id_{t}") for t in ("ssn", "npi", "dl", "license", "email", "vin", "plate", "tin", "cnpi")
            if f"id_{t}" in Xg}
    if part == "person":
        full = lambda F: float(((F["first"] != "") & (F["last"] != "")).mean()) if len(F) else 0.0
        fill["name"] = full(Xg) * full(W)
        fill["dob"] = both("dob")
    else:
        fill["org"] = both("org_aliases")
        fill["zip"] = both("zip")
    fill["street"] = both("addr_street")
    return fill


def _m_lookup(w):
    t = {(f, lev): m for f, lev, m in zip(w["field"], w["level"], w["m"])}
    return lambda f, lev: float(t.get((f, lev), 0.0))


def _replicate_lookups(passes, w, params):
    """m lookups for each bootstrap replicate (mean of the passes' replicate b; the final m
    where no pass saw the field)."""
    reps = min((len(p_["boot"]) for p_ in passes if p_.get("boot")), default=0)
    base = {(f, lev): m for f, lev, m in zip(w["field"], w["level"], w["m"])}
    out = []
    for b in range(reps):
        t = dict(base)
        fields = {f for p_ in passes for f in p_.get("m", {})}
        for f in fields:
            used = [p_ for p_ in passes if f in p_.get("m", {}) and p_.get("boot")]
            if used:
                m = floor_m(np.mean([p_["boot"][b]["m"][f] for p_ in used], axis=0), params)
                for i, lev in enumerate(FIELD_LEVELS[f]):
                    t[(f, lev)] = float(m[i])
        out.append(lambda f, lev, t=t: float(t.get((f, lev), 0.0)))
    return out


def estimate_prior(pr, weights, passes, cfg, log=print, same_frame=False, seed=0):
    """Prior per group (link) or per part (dedup): strict pairs / how often a true match fires
    a strict rule / all pairs, with a bootstrap 95% interval (extracted parties resampled, m
    from the matching EM replicate)."""
    rows, prior = [], {}
    rng = np.random.default_rng(seed)
    ctx = pr.ctx_dedup if same_frame else pr.ctx
    for part in ("person", "business"):
        X, W = pr.X[part], pr.W[part]
        R = X if same_frame else W
        w = weights[part]
        mlook = _m_lookup(w)
        reps = _replicate_lookups(passes.get(part, []), w, cfg.core)
        l, r = strict_pairs(X, W, part, ctx, same_frame)
        per_party = np.bincount(l, minlength=len(X)).astype(float) if len(l) else np.zeros(len(X))
        grp = X["prior_group"].to_numpy() if not same_frame else np.full(len(X), "all", dtype=object)
        for g in (GROUPS if not same_frame else ["all"]):
            gm = grp == g
            if not gm.any():
                continue
            n_strict = int(per_party[gm].sum())
            n_pairs = int(gm.sum()) * (len(R) - 1 if same_frame else len(R))
            if same_frame:
                n_pairs //= 2
            fill = fill_rates(X[gm], R, part)
            rec = strict_recall(fill, mlook)
            pv, flagged = prior_estimate(n_strict, n_pairs, rec, cfg.core)
            boots = []
            if reps:
                cnt = per_party[gm]
                for mb in reps:
                    wts = rng.poisson(1.0, len(cnt)).astype(float)
                    nb = float((wts * cnt).sum())
                    npairs = float(wts.sum()) * (n_pairs / max(1, gm.sum()))
                    boots.append(prior_estimate(nb, npairs, strict_recall(fill, mb), cfg.core)[0])
            lo, hi = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (np.nan, np.nan)
            prior[(part, g)] = pv
            rows.append({"part": part, "group": g, "extracted_parties": int(gm.sum()),
                         "watchlist_parties": len(R), "all_pairs": n_pairs, "strict_pairs": n_strict,
                         "recall": rec, "prior": pv, "prior_lo": lo, "prior_hi": hi,
                         "prior_logit_bits": math.log2(pv / (1 - pv)),
                         "flag": "pseudo-count: no strict pair or no recall" if flagged else ""})
    df = pd.DataFrame(rows)
    log(("dedup " if same_frame else "") + "prior:\n" +
        df[["part", "group", "extracted_parties", "strict_pairs", "recall", "prior", "prior_lo", "prior_hi", "flag"]]
        .to_string(index=False))
    return prior, df


# ---- everything --------------------------------------------------------------------------------
def estimate_models(pr, maps, ref, cfg, wdf, log=print):
    """u, m and the prior for the link model (extracted x watchlist) and the deduplication
    model (extracted x extracted)."""
    rng = np.random.default_rng(cfg.seed)
    nx = {part: len(pr.X[part]) for part in ("person", "business")}
    tot = max(1, sum(nx.values()))
    u = {"link": {}, "dedup": {}}
    comps, n_sample = {}, {"link": {}, "dedup": {}}
    for kind, ctx, same, n_all in (("link", pr.ctx, False, cfg.random_pairs), ("dedup", pr.ctx_dedup, True,
                                                                                   cfg.dedup_random_pairs)):
        for part in ("person", "business"):
            X, W = pr.X[part], pr.W[part]
            if not len(X) or (not same and not len(W)):
                u[kind][part] = estimate_u(pd.DataFrame(), PART_FIELDS[part], cfg.core)
                n_sample[kind][part] = 0
                continue
            n = int(n_all * nx[part] / tot)
            u_df, lv, n_used = estimate_u_model(X, W, part, ctx, n, cfg.seed + (7 if same else 0), same, log,
                                                label=f"{kind} ")
            u[kind][part] = u_df
            n_sample[kind][part] = n_used
            if part == "person" and len(lv):
                comps[kind] = name_components(lv)
        ctx.components = comps.get(kind, {})
    centre, sources, em_loose = prior_centre_m(pr, maps, ref, cfg, wdf, u["link"], rng, log)
    models = {}
    for kind, ctx, same in (("dedup", pr.ctx_dedup, True), ("link", pr.ctx, False)):
        weights, passes = {}, {}
        for part in ("person", "business"):
            X, W = pr.X[part], pr.W[part]
            passes[part] = (run_training(X, W, part, ctx, u[kind][part], centre[part], cfg, rng, same, kind, log)
                            if len(X) and (same or len(W)) else [])
            w = final_weights(part, passes[part], centre[part], u[kind][part], comps.get(kind), cfg.core)
            w.insert(0, "part", part)
            w.insert(0, "model", kind)
            weights[part] = w
        prior, prior_df = estimate_prior(pr, weights, passes, cfg, log, same_frame=same, seed=cfg.seed + 11)
        models[kind] = Model(kind=kind, weights=weights, prior=prior, prior_df=prior_df,
                             passes={part: [{k: v for k, v in p_.items() if k != "boot"} for p_ in ps]
                                     for part, ps in passes.items()},
                             u_sample_pairs=n_sample[kind])
        un = sum(int((w["unstable"] != "").sum()) for w in weights.values())
        log(f"{kind} model: {un} weight levels flagged unstable")
    return {"link": models["link"], "dedup": models["dedup"], "components": comps, "sources": sources,
            "em_loose": em_loose, "centre": centre}
