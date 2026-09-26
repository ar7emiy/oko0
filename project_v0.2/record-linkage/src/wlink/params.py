# %% [markdown]
# ## 8-11 · Comparisons, u, m and the prior
#
# **Comparisons (8).** The core's `compare_pairs` gives one level per field for any set of
# pairs; the same code runs on candidates, random pairs, anchors, watchlist duplicates and
# simulated pairs. Each part (person, business) has its own weights.
#
# **u (9).** `random_pairs` random extracted × watchlist pairs per run (split between parts by
# their share of extracted parties) through the same comparisons give the field-level u of
# every level (Splink's method), and the rates of the name sub-parts. Exact levels use
# value-specific u instead: names from the Census/SSA tables, organization words from NPPES
# (or the watchlist's own share), identifiers, dates and addresses from how many hold the value.
#
# **m (10)**, per field and level, in order of preference:
#
# | Source | Pairs | Used for |
# |---|---|---|
# | 1a strict anchors | extracted pairs sharing a valid one-per-party identifier (SSN, NPI, DL; TIN for businesses) held under exactly one name; at most `anchor_pairs_per_value` pairs per value; same-note pairs excluded | every field except the names (the anchor conditions on the name) and except the anchoring field itself |
# | 1b loose anchors | the same identifier types held by 2-20 extracted parties, no name condition; EM with u fixed and the non-name m fixed from 1a | name, middle, org name |
# | 2 watchlist duplicates | watchlist pairs sharing an SSN / NPI (TIN / clinic NPI) held by 2-20 parties; persons also by exact name + DOB (then not for name or DOB) | fields still short of data |
# | 3 simulation | `sim_records` watchlist rows and their noisy copies (noise table) | any field with < `n_min` informative pairs from 1-2 |
# | 4 published | `mappings/published_m.csv` | the base every estimate is shrunk toward |
#
# Each estimate is shrunk toward the next source with alpha = 5 pseudo-pairs; the manifest
# records the chain, the pairs behind it and a 95% interval. An agreement level whose m falls
# below its u is flagged and counts 0 bits.
#
# **Prior (11)**, per group of the extracted party, over *all* pairs: pairs firing a strict
# rule (single-holder identifier agrees with no veto; exact name + DOB; exact name + street;
# exact org name + ZIP or + street) / how often a true match fires one of them (from the
# estimated m and the fill rates) / all extracted × watchlist pairs of the group. A group with
# no strict pair uses a pseudo-count and is flagged.
#
# **Where Splink would do better.** Splink estimates u from up to 10^8 random pairs in
# DuckDB and trains m with EM in several passes, each blocked on a different rule and with u
# fixed, then averages the passes; here EM runs once, on the loose-anchor set. Splink's prior
# comes from a deterministic-rules count with a user-given recall; here recall is computed from
# the m estimates. Splink does not use anchors or simulation.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.load import *
from wlink.prepare import *
from wlink.simulate import *

ANCHOR_TYPES = {"person": ["ssn", "npi", "dl"], "business": ["tin"]}
NAME_FREE = {"person": ["name", "middle"], "business": ["org"]}
WDUP_TYPES = {"person": ["ssn", "npi"], "business": ["tin", "cnpi"]}


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


def estimate_parameters(pr, maps, ref, cfg, wdf, log=print):
    """u, m, weights per part. Returns dict with weights tables, components, source counts."""
    p = cfg.core
    rng = np.random.default_rng(cfg.seed)
    ctx = pr.ctx
    out = {"weights": {}, "u": {}, "sources": [], "components": None, "em": {}, "random_levels": {}}
    nx = {part: len(pr.X[part]) for part in ("person", "business")}
    tot = max(1, sum(nx.values()))
    # ---- u from random pairs ------------------------------------------------------------
    for part in ("person", "business"):
        t_u = time.time()
        X, W = pr.X[part], pr.W[part]
        n = int(min(cfg.random_pairs * nx[part] / tot, len(X) * len(W)))
        if n <= 0 or not len(X) or not len(W):
            out["u"][part] = estimate_u(pd.DataFrame(), PART_FIELDS[part], p)
            continue
        idx = rl.Index()
        idx.add(rl.index.Random(n, replace=True, random_state=cfg.seed))
        mi = idx.index(X[["party_id"]], W[["party_id"]])
        l, r = mi.get_level_values(0).to_numpy(), mi.get_level_values(1).to_numpy()
        # the frames are positional, so index values are positions
        lv = []
        step = 250_000
        for lo in range(0, len(l), step):
            lv.append(compare_pairs(X, W, l[lo:lo + step], r[lo:lo + step], part, ctx))
        lv = with_coparty(pd.concat(lv, ignore_index=True), X, W, part)
        out["u"][part] = estimate_u(lv, PART_FIELDS[part], p)
        out["random_levels"][part] = len(lv)
        if part == "person":
            out["components"] = name_components(lv)
        log(f"u[{part}]: {len(lv):,} random pairs ({time.time() - t_u:.0f}s)")
    ctx.components = out["components"] or {}
    pub = maps["published_m"]
    pub_arr = lambda f: np.array([float(pub[(pub["field"] == f) & (pub["level"] == lev)]["m"].iloc[0])
                                  for lev in FIELD_LEVELS[f]])
    t0 = time.time()
    # ---- simulation: noisy copies of watchlist rows ----------------------------------------
    k = min(cfg.sim_records, len(wdf))
    pick = np.sort(rng.choice(len(wdf), size=k, replace=False)) if k else np.array([], int)
    src = wdf.iloc[pick][SCHEMA].reset_index(drop=True)
    fake = Fake(ref, rng)
    copies, _ = apply_noise(src, maps["simulation_noise"], fake, rng, scale=1.0, id_prefix="sim")
    nick = ctx.nick
    _, cpar, _, _, _, _ = rows_to_parties(copies, "S", maps, nick, p, False)
    for c in ("id_ssn", "id_npi", "id_dl", "id_license", "id_tin", "id_cnpi", "id_email", "id_vin",
              "id_plate", "phone_own", "phone_row"):
        pass
    C = split_parts(cpar)
    sim_counts = {}
    for part in ("person", "business"):
        Cf, W = C[part], pr.W[part]
        wpos = pd.Series(np.arange(len(W)), index=W["record_id"].to_numpy())
        orig = Cf["record_id"].str.replace("sim:", "", regex=False)
        ok = orig.isin(wpos.index).to_numpy()
        l = np.flatnonzero(ok)
        r = wpos[orig[ok]].to_numpy() if ok.any() else np.array([], np.int64)
        # one watchlist record_id can have both parts; wpos is per part, so ids are unique
        lv = with_coparty(compare_pairs(Cf, W, l, r, part, ctx), Cf, W, part)
        sim_counts[part] = level_counts(lv, PART_FIELDS[part])
        out["sources"].append({"part": part, "source": "simulation", "pairs": len(lv)})
    log(f"simulation: {k:,} noisy copies compared ({time.time() - t0:.0f}s)")
    t0 = time.time()
    # ---- 1a strict anchors, 1b loose anchors (extracted x extracted) ---------------------
    # ---- 2 watchlist duplicates ---------------------------------------------------------
    for part in ("person", "business"):
        X, W = pr.X[part], pr.W[part]
        fields = PART_FIELDS[part]
        non_name = [f for f in fields if f not in NAME_FREE[part]]
        l, r, amask = anchor_pairs(X, ANCHOR_TYPES[part], (2, 10 ** 9), True, cfg.anchor_pairs_per_value, rng)
        lv1 = with_coparty(compare_pairs(X, X, l, r, part, ctx), X, X, part)
        c1a = level_counts(lv1, non_name, exclude=amask)
        out["sources"].append({"part": part, "source": "anchors_strict", "pairs": len(lv1)})
        l, r, dmask = anchor_pairs(W, WDUP_TYPES[part], (2, 20), False, cfg.anchor_pairs_per_value, rng,
                                   exclude_notes=False)
        lv2 = with_coparty(compare_pairs(W, W, l, r, part, ctx), W, W, part)
        c2 = level_counts(lv2, fields, exclude=dmask)
        n_wdup = len(lv2)
        if part == "person":
            l, r = name_dob_pairs(W, cfg.anchor_pairs_per_value, rng)
            lv2b = with_coparty(compare_pairs(W, W, l, r, part, ctx), W, W, part)
            c2b = level_counts(lv2b, [f for f in fields if f not in ("name", "dob")])
            for f, (cnt, n) in c2b.items():
                c0, n0 = c2.get(f, (np.zeros(len(FIELD_LEVELS[f])), 0.0))
                c2[f] = (c0 + cnt, n0 + n)
            n_wdup += len(lv2b)
        out["sources"].append({"part": part, "source": "watchlist_duplicates", "pairs": n_wdup})
        # preliminary m for the fixed (non-name) fields, then EM for the names
        rows = []
        for f in non_name:
            srcs = [("anchors_strict", *c1a.get(f, (None, 0.0))), ("watchlist_duplicates", *c2.get(f, (None, 0.0))),
                    ("simulation", *sim_counts[part].get(f, (None, 0.0)))]
            srcs = [(a, b if b is not None else np.zeros(len(FIELD_LEVELS[f])), c) for a, b, c in srcs]
            rows += combine_m(f, srcs, pub_arr(f), p)
        mfix = pd.DataFrame(rows)
        u_df = out["u"][part]
        l, r, lmask = anchor_pairs(X, ANCHOR_TYPES[part], cfg.loose_holders, False, cfg.anchor_pairs_per_value, rng)
        lv1b = with_coparty(compare_pairs(X, X, l, r, part, ctx), X, X, part)
        fixed = [f for f in non_name if f != "co_party"]
        m_fixed = {f: mfix[mfix["field"] == f].sort_values("level_code")["m"].to_numpy() for f in fixed}
        u_tab = {f: u_df[u_df["field"] == f].sort_values("level_code")["u"].to_numpy() for f in fields if f != "co_party"}
        em, lam, iters = em_fixed_u(lv1b, NAME_FREE[part], fixed, m_fixed, u_tab, p, exclude=lmask)
        out["em"][part] = {"pairs": len(lv1b), "lambda": lam, "iterations": iters}
        out["sources"].append({"part": part, "source": "anchors_loose_em", "pairs": len(lv1b)})
        for f in NAME_FREE[part]:
            cnt, n = (em[f][2], em[f][1]) if f in em else (np.zeros(len(FIELD_LEVELS[f])), 0.0)
            srcs = [("anchors_loose_em", cnt, n), ("watchlist_duplicates", *c2.get(f, (np.zeros(len(FIELD_LEVELS[f])), 0.0))),
                    ("simulation", *sim_counts[part].get(f, (np.zeros(len(FIELD_LEVELS[f])), 0.0)))]
            rows += combine_m(f, srcs, pub_arr(f), p)
        w = weights_table(rows, u_df, out["components"])
        w.insert(0, "part", part)
        out["weights"][part] = w
        log(f"m[{part}]: strict anchors {len(lv1):,}, loose anchors {len(lv1b):,} (EM lambda {lam:.3f}, "
            f"{iters} iterations; {time.time() - t0:.0f}s), watchlist duplicates {n_wdup:,}, simulated {out['sources'][0 if part == 'person' else 1]['pairs']:,}")
    return out


# ---- prior ------------------------------------------------------------------------------------
def strict_pairs(X, W, part, ctx):
    """Extracted x watchlist pairs firing a strict rule (not vetoed), as (l, r)."""
    found = []

    def join(kx, kw):
        a = pd.DataFrame({"k": kx, "l": np.arange(len(X))})
        b = pd.DataFrame({"k": kw, "r": np.arange(len(W))})
        a, b = a[a["k"] != ""], b[b["k"] != ""]
        m = a.merge(b, on="k")
        found.append(m[["l", "r"]])

    single = ctx.stats.single
    ids = ["ssn", "npi", "dl", "license", "email", "vin", "plate"] if part == "person" else ["tin", "cnpi", "email"]
    for t in ids:
        kx = X[f"id_{t}"].to_numpy(dtype=object)
        kx = np.where(pd.Series(kx).isin(single.get(t, set())).to_numpy(), kx, "")
        join(kx, W[f"id_{t}"].to_numpy(dtype=object))
    nk = lambda F: np.where((F["first"] != "") | (F["part"] == "business"), F["name_key"], "").astype(object)
    if part == "person":
        join(np.where(X["dob"] != "", nk(X) + "|" + X["dob"], ""), np.where(W["dob"] != "", nk(W) + "|" + W["dob"], ""))
    else:
        join(np.where(X["zip"] != "", nk(X) + "|" + X["zip"], ""), np.where(W["zip"] != "", nk(W) + "|" + W["zip"], ""))
    join(np.where(X["addr_street"] != "", nk(X) + "|" + X["addr_street"], ""),
         np.where(W["addr_street"] != "", nk(W) + "|" + W["addr_street"], ""))
    f = pd.concat(found, ignore_index=True).drop_duplicates()
    if not len(f):
        return f["l"].to_numpy(), f["r"].to_numpy()
    lv = compare_pairs(X, W, f["l"].to_numpy(), f["r"].to_numpy(), part, ctx)
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


def estimate_prior(pr, params_out, cfg, log=print):
    rows = []
    prior = {}
    for part in ("person", "business"):
        X, W = pr.X[part], pr.W[part]
        w = params_out["weights"][part]
        mlook = lambda f, lev: float(w[(w["field"] == f) & (w["level"] == lev)]["m"].iloc[0]) if ((w["field"] == f) & (w["level"] == lev)).any() else 0.0
        l, r = strict_pairs(X, W, part, pr.ctx)
        grp = X["prior_group"].to_numpy()
        for g in GROUPS:
            gm = grp == g
            if not gm.any():
                continue
            n_strict = int(gm[l].sum()) if len(l) else 0
            n_pairs = int(gm.sum()) * len(W)
            fill = fill_rates(X[gm], W, part)
            rec = strict_recall(fill, mlook)
            pv, flagged = prior_estimate(n_strict, n_pairs, rec, cfg.core)
            prior[(part, g)] = pv
            rows.append({"part": part, "group": g, "extracted_parties": int(gm.sum()),
                         "watchlist_parties": len(W), "all_pairs": n_pairs, "strict_pairs": n_strict,
                         "recall": rec, "prior": pv, "prior_logit_bits": math.log2(pv / (1 - pv)),
                         "flag": "pseudo-count: no strict pair or no recall" if flagged else ""})
    df = pd.DataFrame(rows)
    log(df[["part", "group", "extracted_parties", "strict_pairs", "recall", "prior", "flag"]].to_string(index=False))
    return prior, df
