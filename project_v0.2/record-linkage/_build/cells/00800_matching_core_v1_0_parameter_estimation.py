# ---- Matching core v1.1: parameter estimation ------------------------------------------------
# u: exact-agreement levels in closed form from value frequencies over all pairs (no sampling);
# the fuzzy levels from a very large random sample, rescaled to the probability the closed form
# leaves. m: a prior centre from level counts per source (anchors, watchlist duplicates,
# simulation, published values, shrunk in a chain), then Splink-style EM with u fixed in several
# training passes, each blind to the fields its pairs were selected on, with a Dirichlet prior
# (a Beta per level) toward that centre, bootstrapped intervals, a floor on m and bounded bits.


def level_counts(levels, fields, weights=None, exclude=None):
    """Counts of each level among informative pairs (level != EMPTY). `exclude[field]` is a
    boolean mask of pairs whose value of that field must not count (the anchor's own field).
    Returns {field: (counts array per level, informative total)}."""
    out = {}
    w = np.ones(len(levels)) if weights is None else np.asarray(weights, dtype=float)
    for f in fields:
        if f not in levels:
            continue
        lv = levels[f].to_numpy()
        ok = lv >= 0
        if exclude is not None and f in exclude:
            ok &= ~exclude[f]
        k = len(FIELD_LEVELS[f])
        counts = np.bincount(lv[ok].astype(np.int64), weights=w[ok], minlength=k)[:k]
        out[f] = (counts, float(w[ok].sum()))
    return out


def estimate_u(levels_random, fields, params):
    """Field-level u per level from random pairs, smoothed by a pseudo-count."""
    rows = []
    cnt = level_counts(levels_random, fields)
    for f in fields:
        counts, n = cnt.get(f, (np.zeros(len(FIELD_LEVELS[f])), 0.0))
        k = len(counts)
        u = (counts + params.u_pseudo) / (n + params.u_pseudo * k)
        for i, lev in enumerate(FIELD_LEVELS[f]):
            rows.append({"field": f, "level": lev, "level_code": i, "u": float(u[i]),
                         "u_count": float(counts[i]), "u_pairs": float(n),
                         "u_source": f"random pairs ({int(n):,} informative)", "u_method": "sample"})
    return pd.DataFrame(rows)


# ---- u in closed form ------------------------------------------------------------------------
def _keys(frame, cols):
    """One key per party joining `cols`; '' when any part is empty (a joint key agrees only when
    every part agrees and none is empty)."""
    if isinstance(cols, str):
        cols = [cols]
    arrs = [frame[c].to_numpy(dtype=object) if c in frame else np.full(len(frame), "", dtype=object)
            for c in cols]
    out = arrs[0].astype(object)
    ok = out != ""
    for a in arrs[1:]:
        ok &= a != ""
        out = out + "\x1f" + a
    return np.where(ok, out, "")


def agreement_count(kx, kw=None):
    """Pairs whose keys agree, from value frequencies alone: sum over values of cx * cw between
    two frames, or cx (cx - 1) / 2 among distinct parties of one frame (kw None). kx, kw: key
    arrays ('' = none) or lists of key arrays for multi-valued fields (a party is counted once
    per value it holds)."""
    def vc(k):
        if isinstance(k, list):
            parts = [pd.DataFrame({"i": np.arange(len(a)), "v": np.asarray(a, dtype=object)}) for a in k]
            d = pd.concat(parts, ignore_index=True)
            d = d[d["v"] != ""].drop_duplicates()
            return d["v"].value_counts()
        s = pd.Series(np.asarray(k, dtype=object))
        return s[s != ""].value_counts()
    cx = vc(kx).astype(float)
    if kw is None:
        return float((cx * (cx - 1) / 2).sum())
    cw = vc(kw).astype(float)
    common = cx.index.intersection(cw.index)
    return float((cx[common] * cw[common]).sum())


def _pair_count(mask_x, mask_w=None):
    nx = float(np.asarray(mask_x, bool).sum())
    if mask_w is None:
        return nx * (nx - 1) / 2
    return nx * float(np.asarray(mask_w, bool).sum())


def _pattern_pairs(px, pw=None):
    """Pairs whose patterns (small ints, bit flags of which parts are filled) share a filled
    part: the informative pairs of a group field."""
    cx = pd.Series(px).value_counts()
    if pw is None:
        tot = 0.0
        items = list(cx.items())
        for i, (a, na) in enumerate(items):
            for b, nb in items[i:]:
                if a & b:
                    tot += na * (na - 1) / 2 if a == b else na * nb
        return tot
    cw = pd.Series(pw).value_counts()
    return float(sum(na * nb for a, na in cx.items() for b, nb in cw.items() if a & b))


def _hierarchy(keys_x, keys_w, same):
    """Probability mass (as pair counts) of each level of a field whose levels are 'key i
    agrees and no earlier key agrees' (address, specialty + category), by inclusion-exclusion
    over joint keys. keys_x / keys_w: list of key arrays best-first."""
    from itertools import combinations
    out = []
    for i in range(len(keys_x)):
        tot = 0.0
        earlier = list(range(i))
        for r in range(len(earlier) + 1):
            for S in combinations(earlier, r):
                idx = (i,) + S

                def joint(keys):
                    k = keys[idx[0]]
                    ok = k != ""
                    out_ = k.astype(object)
                    for j in idx[1:]:
                        ok &= keys[j] != ""
                        out_ = out_ + "\x1e" + keys[j]
                    return np.where(ok, out_, "")
                c = agreement_count(joint(keys_x), None if same else joint(keys_w))
                tot += (-1) ** r * c
        out.append(max(0.0, tot))
    return out


def closed_form_u(left, right, part, single_phone=None, same_frame=False):
    """Exact-agreement u per field in closed form: agreeing pairs over all informative pairs,
    counted from value frequencies (no sampling). `same_frame`: left and right are one frame
    (deduplication); pairs are distinct parties. Returns {field: {level: (u, informative
    pairs)}} for the levels it can count exactly; the fuzzy levels come from the sample."""
    L, R_ = left, (left if same_frame else right)
    same = same_frame
    kw = (lambda cols: None) if same else (lambda cols: _keys(R_, cols))
    out = {}

    def simple(field_, col):
        kx_, kw_ = _keys(L, col), (None if same else _keys(R_, col))
        n = _pair_count(kx_ != "", None if same else kw_ != "")
        if n > 0:
            out[field_] = {"exact": (agreement_count(kx_, kw_) / n, n)}
    for f in ("ssn", "npi", "tin", "email", "vin", "cnpi"):
        if f in PART_FIELDS[part]:
            simple(f, f"id_{f}")
    for f in ("dl", "license", "plate"):
        if f in PART_FIELDS[part] and f"id_{f}" in L:
            num = lambda F: np.array([v.partition(":")[2] if v else "" for v in F[f"id_{f}"].to_numpy(dtype=object)],
                                     dtype=object)
            kx_, kw_ = num(L), (None if same else num(R_))
            n = _pair_count(kx_ != "", None if same else kw_ != "")
            if n > 0:
                out[f] = {"exact": (agreement_count(kx_, kw_) / n, n)}
    if part == "person":
        simple("dob", "dob")
        lx = _keys(L, "last")
        n = _pair_count(lx != "", None if same else _keys(R_, "last") != "")
        if n > 0:
            out["name"] = {"exact": (agreement_count(_keys(L, ["first", "last"]),
                                                     None if same else _keys(R_, ["first", "last"])) / n, n)}
    else:
        ax = [np.array([(s.split("|") + [""] * 4)[i] if s else "" for s in L["org_aliases"]], dtype=object)
              for i in range(4)]
        aw = None if same else [np.array([(s.split("|") + [""] * 4)[i] if s else "" for s in R_["org_aliases"]],
                                         dtype=object) for i in range(4)]
        n = _pair_count(L["org_aliases"] != "", None if same else R_["org_aliases"] != "")
        if n > 0:
            out["org"] = {"exact": (min(1.0, agreement_count(ax, aw) / n), n)}
    # address: exact / street / zip / city_state / state, one hierarchy; informative when a
    # state, a ZIP or a street is on both sides
    cols = ["addr_full", "addr_street", "zip", "city_state", "state"]
    pat = lambda F: ((F["state"] != "").astype(int) + 2 * (F["zip"] != "").astype(int)
                     + 4 * (F["addr_street"] != "").astype(int)).to_numpy()
    n = _pattern_pairs(pat(L), None if same else pat(R_))
    if n > 0:
        h = _hierarchy([_keys(L, c) for c in cols], None if same else [_keys(R_, c) for c in cols], same)
        out["address"] = {lev: (c / n, n) for lev, c in zip(FIELD_LEVELS["address"][:5], h)}
    # specialty + category: specialty / category, both strong / category, one weak
    def sc_keys(F):
        cat = np.where(F["category"].to_numpy(dtype=object) == "other", "", F["category"].to_numpy(dtype=object))
        strong = np.where(F["cat_strength"].to_numpy(dtype=object) == "strong", cat, "")
        return [F["specialty"].to_numpy(dtype=object), strong.astype(object), cat.astype(object)]
    kx_ = sc_keys(L)
    kw_ = None if same else sc_keys(R_)
    patf = lambda k: (k[2] != "").astype(int) + 2 * (k[0] != "").astype(int)
    n = _pattern_pairs(patf(kx_), None if same else patf(kw_))
    if n > 0:
        h = _hierarchy(kx_, kw_, same)
        out["spec_cat"] = {"specialty": (h[0] / n, n), "category_id": (h[1] / n, n), "category_weak": (h[2] / n, n)}
    # phones: any number agreeing (owned or row-level); the owned, single-holder share apart
    has = lambda F: (F["phone_own"] != "") | (F["phone_row"] != "")
    n = _pair_count(has(L), None if same else has(R_))
    if n > 0:
        anyx = [L["phone_own"].to_numpy(dtype=object), L["phone_row"].to_numpy(dtype=object)]
        anyw = None if same else [R_["phone_own"].to_numpy(dtype=object), R_["phone_row"].to_numpy(dtype=object)]
        single = single_phone or set()
        own1 = lambda F: np.array([v if v in single else "" for v in F["phone_own"].to_numpy(dtype=object)], dtype=object)
        a_own = agreement_count(own1(L), None if same else own1(R_))
        a_any = agreement_count(anyx, anyw)
        out["phone"] = {"exact_owned_single": (a_own / n, n), "exact_shared": (max(0.0, a_any - a_own) / n, n)}
    return out


def combine_u(u_sample, closed, field_, params=None):
    """u per level of one field: closed-form levels as counted (with the same pseudo-count as
    the sample, so a level never seen among all pairs is rare, not impossible); the others
    from the sample, rescaled so every level sums to 1. `u_sample`: estimate_u rows."""
    params = params or CoreParams()
    s = u_sample[u_sample["field"] == field_].sort_values("level_code").copy()
    cf = closed.get(field_, {})
    if not cf:
        return s
    fixed = np.array([lev in cf for lev in s["level"]])
    k = len(s)
    cf_u = np.array([(cf[lev][0] * cf[lev][1] + params.u_pseudo) / (cf[lev][1] + params.u_pseudo * k)
                     if lev in cf else 0.0 for lev in s["level"]])
    rest = s["u"].to_numpy()
    room = max(0.0, 1.0 - cf_u.sum())
    tot_rest = rest[~fixed].sum()
    u = np.where(fixed, np.maximum(cf_u, 1e-15), rest * (room / tot_rest if tot_rest > 0 else 0.0))
    n = next(iter(cf.values()))[1]
    s["u"] = np.maximum(u, 1e-15)
    s["u_method"] = np.where(fixed, "closed form", "sample, rescaled")
    s["u_source"] = np.where(fixed, f"closed form over all {n:,.0f} informative pairs (value frequencies)",
                             s["u_source"] + " rescaled to the mass the closed form leaves")
    s["u_pairs"] = np.where(fixed, n, s["u_pairs"])
    return s


def name_components(levels_random):
    """Random-pair rates of the name sub-parts (first-name part given informative names, and
    'last name close' / 'sounds alike'), for the value-specific u of the partial name levels."""
    ok = levels_random["name"].to_numpy() >= 0 if "name" in levels_random else np.zeros(0, bool)
    n = max(1, int(ok.sum()))
    fc = levels_random["name_first_cmp"].to_numpy()[ok] if ok.any() else np.array([], dtype=int)
    lc = levels_random["name_last_cmp"].to_numpy()[ok] if ok.any() else np.array([], dtype=int)
    rate = lambda mask: (float(mask.sum()) + 0.5) / (n + 1.0)
    return {"first_nick": rate(fc == 1), "first_close": rate(fc == 2),
            "first_agrees_fuzzy": rate((fc == 1) | (fc == 2)), "first_initial": rate(fc == 3),
            "first_empty": rate(fc == 4), "first_differs": rate(fc == 5),
            "last_close": rate(lc == 1), "last_sound": rate(lc == 2), "pairs": n}


# ---- EM --------------------------------------------------------------------------------------
def em_fixed_u(levels, free_fields, fixed_fields, m_fixed, u_table, params, exclude=None):
    """Expectation-maximization over the pairs in `levels`, with u fixed for every field and m
    fixed for `fixed_fields`; learns m for `free_fields` and the match share lambda.
    `m_fixed[f]` and `u_table[f]` are arrays per level. Returns ({field: (m array, n_eff,
    expected counts)}, lambda, iterations). Used for the loose-anchor name estimate that
    centres the prior; the training passes use em_patterns."""
    n = len(levels)
    if n == 0:
        return {}, float("nan"), 0
    fields = [f for f in list(free_fields) + list(fixed_fields) if f in levels]
    lv = {f: levels[f].to_numpy().astype(np.int64) for f in fields}
    ok = {f: (lv[f] >= 0) & (~exclude[f] if exclude is not None and f in exclude else True)
          for f in fields}
    m = {f: (np.asarray(m_fixed[f], dtype=float) if f in fixed_fields
             else np.linspace(0.9, 0.1, len(FIELD_LEVELS[f])) / np.linspace(0.9, 0.1, len(FIELD_LEVELS[f])).sum())
         for f in fields}
    u = {f: np.asarray(u_table[f], dtype=float) for f in fields}
    lam, it = 0.5, 0
    for it in range(1, params.em_max_iter + 1):
        log_m = np.zeros(n)
        log_u = np.zeros(n)
        for f in fields:
            idx = np.where(ok[f], lv[f], 0)
            log_m += np.where(ok[f], np.log(np.clip(m[f][idx], 1e-12, 1)), 0.0)
            log_u += np.where(ok[f], np.log(np.clip(u[f][idx], 1e-12, 1)), 0.0)
        a = np.log(lam) + log_m
        b = np.log(1 - lam) + log_u
        w = 1.0 / (1.0 + np.exp(np.clip(b - a, -700, 700)))
        new_lam = float(np.clip(w.mean(), 1e-6, 1 - 1e-6))
        delta = abs(new_lam - lam)
        for f in free_fields:
            if f not in lv:
                continue
            k = len(FIELD_LEVELS[f])
            c = np.bincount(lv[f][ok[f]], weights=w[ok[f]], minlength=k)[:k]
            tot = c.sum()
            if tot > 0:
                newm = (c + 1e-3) / (tot + 1e-3 * k)
                delta = max(delta, float(np.abs(newm - m[f]).max()))
                m[f] = newm
        lam = new_lam
        if delta < params.em_tol:
            break
    out = {}
    for f in free_fields:
        if f in lv:
            out[f] = (m[f], float(w[ok[f]].sum()), np.bincount(lv[f][ok[f]], weights=w[ok[f]],
                                                             minlength=len(FIELD_LEVELS[f]))[:len(FIELD_LEVELS[f])])
    return out, lam, it


def pattern_table(levels, fields):
    """Distinct level patterns over `fields` (rows; -1 = null level) and how many pairs show
    each. EM and its bootstrap run on this table, so their cost does not grow with the pairs."""
    fields = [f for f in fields if f in levels]
    if not len(levels) or not fields:
        return np.zeros((0, len(fields)), np.int64), np.zeros(0), fields
    arr = np.stack([levels[f].to_numpy().astype(np.int64) for f in fields], axis=1)
    uniq, counts = np.unique(arr, axis=0, return_counts=True)
    return uniq, counts.astype(float), fields


def em_patterns(pat, counts, fields, u_tab, m_prior, alpha, params, m_init=None, lam_init=0.05,
                max_iter=None, tol=None):
    """EM with u fixed, over level patterns weighted by their counts. The null level (-1)
    carries no information for either class. m gets a Dirichlet prior centred on `m_prior`
    with `alpha` pseudo-pairs (a Beta prior per level): m_k = (E[n_k] + alpha m0_k) /
    (E[n] + alpha), so a field seen in few matches shrinks toward the centre.
    Returns {"m": {f: array}, "lambda", "iterations", "converged", "n_match": {f: expected
    informative matches}}."""
    max_iter = max_iter or params.em_max_iter
    tol = tol or params.em_tol
    if not len(pat) or counts.sum() <= 0:
        return {"m": {f: np.asarray(m_prior[f], float) for f in fields}, "lambda": float("nan"),
                "iterations": 0, "converged": False, "n_match": {f: 0.0 for f in fields}}
    m = {f: np.asarray((m_init or m_prior)[f], dtype=float).copy() for f in fields}
    m0 = {f: np.asarray(m_prior[f], dtype=float) for f in fields}
    u = {f: np.clip(np.asarray(u_tab[f], dtype=float), 1e-15, 1.0) for f in fields}
    cols = {f: pat[:, j] for j, f in enumerate(fields)}
    okc = {f: cols[f] >= 0 for f in fields}
    idx = {f: np.where(okc[f], cols[f], 0) for f in fields}
    log_u = np.zeros(len(pat))
    for f in fields:
        log_u += np.where(okc[f], np.log(u[f][idx[f]]), 0.0)
    lam, it, converged = float(lam_init), 0, False
    tot = counts.sum()
    nm = {}
    for it in range(1, max_iter + 1):
        log_m = np.zeros(len(pat))
        for f in fields:
            log_m += np.where(okc[f], np.log(np.clip(m[f][idx[f]], 1e-15, 1.0)), 0.0)
        a = math.log(lam) + log_m
        b = math.log(1 - lam) + log_u
        w = 1.0 / (1.0 + np.exp(np.clip(b - a, -700, 700)))
        wc = w * counts
        new_lam = float(np.clip(wc.sum() / tot, 1e-9, 1 - 1e-9))
        delta = abs(new_lam - lam) / max(lam, 1e-9)
        for f in fields:
            k = len(FIELD_LEVELS[f])
            c = np.bincount(cols[f][okc[f]], weights=wc[okc[f]], minlength=k)[:k]
            newm = (c + alpha * m0[f]) / (c.sum() + alpha)
            delta = max(delta, float(np.abs(newm - m[f]).max()))
            m[f] = newm
            nm[f] = float(c.sum())
        lam = new_lam
        if delta < tol:
            converged = True
            break
    return {"m": m, "lambda": lam, "iterations": it, "converged": converged, "n_match": nm}


def training_pass_em(levels, fields, u_tab, m_prior, params, name, rng=None, reps=0):
    """One Splink-style training pass: EM with u fixed on pairs chosen by one rule, over the
    fields the rule did not use. With reps > 0, also a bootstrap: pattern counts resampled
    (multinomial) and EM rerun from the point estimate. Returns the point estimate and the
    replicate m's."""
    pat, counts, fields = pattern_table(levels, fields)
    alpha = params.em_prior_strength
    est = em_patterns(pat, counts, fields, u_tab, m_prior, alpha, params)
    est.update({"pass": name, "pairs": int(counts.sum()), "patterns": len(pat), "fields": list(fields)})
    boots = []
    if reps and len(pat) and counts.sum() > 0:
        n = int(counts.sum())
        prob = counts / counts.sum()
        for _ in range(reps):
            cb = rng.multinomial(n, prob).astype(float)
            b = em_patterns(pat, cb, fields, u_tab, m_prior, alpha, params, m_init=est["m"],
                            lam_init=est["lambda"], max_iter=200, tol=1e-6)
            boots.append({"m": b["m"], "lambda": b["lambda"]})
    est["boot"] = boots
    return est


def combine_passes(passes, field_, m_prior, u, params):
    """One field's m from the training passes that saw it: the mean of the passes' estimates
    (Splink's rule), each already carrying the Dirichlet prior; the prior centre when no pass
    saw the field. 95% interval from the bootstrap (replicate b averages replicate b of every
    pass). Returns (m, lo, hi, per-pass m dict, bits lo, bits hi, flags)."""
    k = len(FIELD_LEVELS[field_])
    used = [p for p in passes if field_ in p["m"] and p["pairs"] > 0 and p.get("n_match", {}).get(field_, 0) > 0]
    m0 = np.asarray(m_prior, dtype=float)
    if not used:
        nan = np.full(k, np.nan)
        return m0, nan, nan, {}, nan, nan, ["no training pass saw this field: prior centre only"], np.zeros(k)
    m = np.mean([p["m"][field_] for p in used], axis=0)
    per = {p["pass"]: p["m"][field_] for p in used}
    reps = min((len(p["boot"]) for p in used), default=0)
    flags = []
    if reps:
        R_ = np.array([floor_m(np.mean([p["boot"][b]["m"][field_] for p in used], axis=0), params)
                       for b in range(reps)])
        lo, hi = np.percentile(R_, 2.5, axis=0), np.percentile(R_, 97.5, axis=0)
        bits_r = np.clip(np.log2(np.clip(R_, 1e-15, 1) / np.clip(u, 1e-15, 1)), params.bits_min, params.bits_max)
        blo, bhi = np.percentile(bits_r, 2.5, axis=0), np.percentile(bits_r, 97.5, axis=0)
    else:
        lo = hi = blo = bhi = np.full(k, np.nan)
    if len(used) > 1:
        bits_p = np.array([np.clip(np.log2(np.clip(floor_m(p["m"][field_], params), 1e-15, 1) / np.clip(u, 1e-15, 1)),
                                   params.bits_min, params.bits_max) for p in used])
        spread = bits_p.max(axis=0) - bits_p.min(axis=0)
    else:
        spread = np.zeros(k)
    for p in used:
        if not p["converged"]:
            flags.append(f"pass {p['pass']} did not converge")
    return m, lo, hi, per, blo, bhi, flags, spread


def combine_m(field_, sources, published, params):
    """One field's prior-centre m per level from sources in preference order.

    `sources`: list of (name, counts array, informative n) best first. Each estimate is shrunk
    toward the next one (alpha pseudo-pairs), bottom-up from the published value. Simulation
    (a source named 'simulation') joins the chain only when the sources before it hold fewer
    than n_min informative pairs. Returns rows with m, the chain, pairs and a 95% interval."""
    k = len(FIELD_LEVELS[field_])
    pub = np.asarray(published, dtype=float)
    pub = pub / pub.sum() if pub.sum() > 0 else np.full(k, 1.0 / k)
    before_sim = 0.0
    used = []
    for name, counts, n in sources:
        if name == "simulation" and before_sim >= params.n_min:
            continue
        if n > 0:
            used.append((name, np.asarray(counts, dtype=float), float(n)))
        if name != "simulation":
            before_sim += n
    m = pub.copy()
    for name, counts, n in reversed(used):
        m = (counts + params.alpha * m) / (n + params.alpha)
    n_total = sum(n for _, _, n in used)
    n_eff = n_total + params.alpha
    se = np.sqrt(np.clip(m * (1 - m), 0, None) / n_eff)
    chain = " > ".join(f"{name}({n:,.0f})" for name, _, n in used) or "published only"
    primary = used[0][0] if used else "published"
    rows = []
    for i, lev in enumerate(FIELD_LEVELS[field_]):
        rows.append({"field": field_, "level": lev, "level_code": i, "m": float(m[i]),
                     "m_lo": float(max(0.0, m[i] - params.ci_z * se[i])),
                     "m_hi": float(min(1.0, m[i] + params.ci_z * se[i])),
                     "m_source": primary, "m_chain": chain, "m_pairs": float(n_total),
                     "m_published": float(pub[i])})
    return rows


def floor_m(m, params):
    """No level below params.m_floor (then renormalized): bounds every disagreement weight."""
    m = np.maximum(np.asarray(m, dtype=float), params.m_floor)
    return m / m.sum()


def weights_table(m_rows, u_df, components, params=None):
    """Join m and u per field and level; field-level bits; flag agreement levels where m < u
    (those count 0 bits), disagreement levels where m > u, and unstable estimates. Value-specific
    levels say what their u rests on."""
    params = params or CoreParams()
    w = pd.DataFrame(m_rows).merge(u_df, on=["field", "level", "level_code"], how="left")
    w["u"] = w["u"].fillna(1.0)
    w["agreement"] = [lev in AGREEMENT_LEVELS.get(f, set()) for f, lev in zip(w["field"], w["level"])]
    w["zero_by_rule"] = [lev in ZERO_LEVELS.get(f, set()) for f, lev in zip(w["field"], w["level"])]
    w["bits_field_level"] = np.clip(np.log2(np.clip(w["m"], 1e-12, 1) / np.clip(w["u"], 1e-12, 1)),
                                    params.bits_min, params.bits_max)
    w["disagreement"] = [lev in DISAGREEMENT_LEVELS.get(f, set()) for f, lev in zip(w["field"], w["level"])]
    flag = np.where(w["agreement"] & (w["m"] < w["u"]), "m<u: agreement counts 0 bits",
                    np.where(w["disagreement"] & (w["m"] > w["u"]), "m>u: disagreement counts 0 bits", ""))
    if "unstable" in w:
        flag = np.where(w["unstable"].fillna("") != "",
                        np.where(flag != "", flag + "; ", "") + "UNSTABLE: " + w["unstable"].fillna(""), flag)
    w["flag"] = flag
    w["u_value_specific"] = [value_specific(f, lev) for f, lev in zip(w["field"], w["level"])]
    return w


VALUE_U_SOURCE = {
    ("name", "exact"): "census surname x SSA first name, or the list's own share of the full name if larger (per value)",
    ("name", "first_nick"): "census surname (per value) x random-pair rate of a nickname first name",
    ("name", "first_close"): "census surname (per value) x random-pair rate of a close first name",
    ("name", "last_close_first_agrees"): "random-pair rate of a close surname x SSA first name (per value)",
    ("name", "last_sound_first_agrees"): "random-pair rate of a like-sounding surname x SSA first name (per value)",
    ("name", "initial_agrees"): "census surname x SSA share of the initial (per value)",
    ("name", "swapped"): "census x SSA for the swapped values",
    ("name", "first_empty"): "census surname (per value) x random-pair rate of an empty first name",
    ("name", "first_differs"): "census surname (per value) x random-pair rate of a differing first name",
    ("org", "exact"): "NPPES / reference-population word shares (per value)",
    ("org", "dba"): "NPPES / reference-population word shares (per value)",
    ("org", "short_form"): "NPPES / reference-population word shares of the shared words",
    ("org", "close"): "NPPES / reference-population word shares of the shared words",
    ("org", "rare_shared"): "NPPES / reference-population share of the rarest shared word",
    ("dob", "exact"): "reference population: holders of the date",
    ("address", "exact"): "reference population: holders of the address",
    ("address", "street"): "reference population: holders of number + street",
    ("address", "zip"): "reference population: holders of the ZIP",
    ("address", "city_state"): "reference population: holders of city + state",
    ("address", "state"): "reference population: holders of the state",
    ("spec_cat", "specialty"): "reference population: holders of the specialty",
    ("spec_cat", "category_id"): "reference population: holders of the category",
    ("spec_cat", "category_weak"): "reference population: holders of the category",
}
for _f in IDENTIFIER_FIELDS:
    VALUE_U_SOURCE[(_f, "exact" if _f != "phone" else "exact_owned_single")] = "distinct names holding the value / reference holders of the field"
VALUE_U_SOURCE[("phone", "exact_shared")] = "distinct names holding the value / reference holders of the field"


def value_specific(f, lev):
    return VALUE_U_SOURCE.get((f, lev), "")


def strict_recall(fill, m_lookup):
    """How often a true match fires at least one strict rule, from field fill rates and the
    estimated m (rules treated as independent). `fill[key]`: share of pairs where both sides
    hold the field; `m_lookup(field, level)`: estimated m."""
    q = []
    ids = [f for f in ("ssn", "npi", "dl", "tin", "license", "email", "vin", "plate", "cnpi")]
    for f in ids:
        if fill.get(f, 0) > 0:
            q.append(fill[f] * m_lookup(f, "exact"))
    if fill.get("name", 0) > 0:
        q.append(fill["name"] * fill.get("dob", 0) * m_lookup("name", "exact") * m_lookup("dob", "exact"))
        q.append(fill["name"] * fill.get("street", 0) * m_lookup("name", "exact")
                 * (m_lookup("address", "exact") + m_lookup("address", "street")))
    if fill.get("org", 0) > 0:
        q.append(fill["org"] * fill.get("zip", 0) * m_lookup("org", "exact")
                 * (m_lookup("address", "exact") + m_lookup("address", "zip")))
        q.append(fill["org"] * fill.get("street", 0) * m_lookup("org", "exact")
                 * (m_lookup("address", "exact") + m_lookup("address", "street")))
    return float(1 - np.prod([1 - min(1.0, x) for x in q])) if q else 0.0


def prior_estimate(n_strict, n_pairs, recall, params):
    """P(a random pair of the group matches) = strict pairs / recall / all pairs. A zero count
    uses a pseudo-count and is flagged."""
    flagged = n_strict == 0 or recall <= 0
    num = (n_strict if n_strict > 0 else params.prior_pseudo) / max(recall, 1e-3)
    prior = float(min(0.5, num / max(1.0, float(n_pairs))))
    return prior, flagged
