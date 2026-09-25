# %% [markdown]
# ## 12 · Score
#
# In chunks of extracted parties: candidates → comparisons → the core's Fellegi-Sunter scorer
# (sum of log2(m/u) per field, value-specific u on the levels that have one, 0 bits when a field
# is empty, agreement never below 0) → vetoes (p = 0, visible, with the reason) → basis.
# Businesses are scored first; their identifier links at p >= 0.9 with no veto are the anchors
# for the **co-party** pass on persons, which adds bits only where the names already agree
# (one way: a co-party can strengthen a name, never make one, and name-only links never vouch
# for each other).
#
# A pair is **kept** when p >= `keep_p_floor`, or it is among its entity's top K (ties kept), or
# it rests on an identifier, or it is vetoed. Pairs are never filtered by basis: a name-only
# match is kept on the same terms as any other.
#
# **Where Splink would do better.** Splink's `predict()` scores every blocked pair in SQL with
# term-frequency adjustments and writes them all; the keep rule here exists because the output
# is a workbook. Splink has no vetoes or basis classes: both are ours.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.prepare import *
from wlink.candidates import *
from wlink.category import GROUPS

P_BINS = np.array([0, 1e-3, 0.01, 0.1, 0.5, 0.8, 0.9, 0.99, 1.0000001])


def _rank_within(l, p):
    """Rank of each pair within its entity (l), best first; ties share the rank ('min')."""
    d = pd.DataFrame({"l": l, "p": p})
    return d.groupby("l")["p"].rank(method="min", ascending=False).to_numpy()


def score_part(pr, part, weights, prior, cfg, anchors=None, log=print):
    """Score every candidate of one part. Returns (kept pairs frame, kept levels frame,
    per-entity summary, diagnostics)."""
    X, W = pr.X[part], pr.W[part]
    ctx = pr.ctx
    plan = CandidatePlan(X, W, part, ctx.rarity, cfg, ctx.dba_pairs)
    for rep in plan.report:
        log(f"  {part:<8} {rep['rule']:<22} pairs {rep['pairs_before_refine']:>12,}"
            + (f"  oversized keys {rep['oversized_keys']} -> dropped {rep['dropped_keys']} ({rep['dropped_pairs']:,} pairs)"
               if rep['oversized_keys'] or rep['dropped_keys'] else ""))
    grp_logit = {g: math.log2(prior[(part, g)] / (1 - prior[(part, g)])) for g in GROUPS if (part, g) in prior}
    x_logit = X["prior_group"].map(grp_logit).fillna(0.0).to_numpy(dtype=float)
    kept_s, kept_l, summ, all_keys = [], [], [], []
    hist = np.zeros((len(BASIS_ORDER), len(P_BINS) - 1), dtype=np.int64)
    n_scored = 0
    rule_counts = defaultdict(int)
    for lo in range(0, len(X), cfg.chunk_size):
        hi = min(len(X), lo + cfg.chunk_size)
        c = plan.chunk(lo, hi)
        if not len(c):
            continue
        l, r = c["l"].to_numpy(), c["r"].to_numpy()
        all_keys.append(l.astype(np.int64) * np.int64(1 << 32) + r)
        for name, bit in plan.bit.items():
            rule_counts[name] += int(((c["rules"].to_numpy() & bit) > 0).sum())
        lv = compare_pairs(X, W, l, r, part, ctx)
        pl = x_logit[l]
        if part == "person":
            tl, tr = X["tie_pos"].to_numpy()[l], W["tie_pos"].to_numpy()[r]
            lv["co_party"] = np.where((tl >= 0) & (tr >= 0), 1, EMPTY).astype(np.int8)
            sc = score_pairs(lv, part, weights, pl)
            anch = np.zeros(len(lv), bool)
            if anchors is not None and len(anchors):
                has = (tl >= 0) & (tr >= 0)
                anch[has] = np.isin(tl[has].astype(np.int64) * np.int64(1 << 32) + tr[has], anchors)
            if anch.any():
                lv, sc = apply_coparty(lv, sc, weights, pl, anch)
        else:
            sc = score_pairs(lv, part, weights, pl)
        n_scored += len(sc)
        p = sc["p"].to_numpy()
        basis = sc["basis"].to_numpy()
        bi = pd.Series(basis).map({b: i for i, b in enumerate(BASIS_ORDER)}).to_numpy()
        pbin = np.clip(np.searchsorted(P_BINS, p, side="right") - 1, 0, len(P_BINS) - 2)
        vetoed = sc["veto"].to_numpy() != ""
        np.add.at(hist, (bi[~vetoed], pbin[~vetoed]), 1)
        # rank among non-vetoed candidates of the entity
        pr_rank = np.where(vetoed, -1.0, p)
        rank = _rank_within(l, pr_rank)
        keep = (p >= cfg.keep_p_floor) | (rank <= cfg.top_k) | (basis == "identifier") | vetoed
        s = sc[keep].copy()
        s.insert(0, "rank", np.where(vetoed[keep], np.nan, rank[keep]))
        s.insert(0, "rules", plan.rule_names(c["rules"].to_numpy()[keep]))
        s.insert(0, "r", r[keep]); s.insert(0, "l", l[keep])
        s["prior_logit"] = pl[keep]
        kept_s.append(s.reset_index(drop=True))
        kept_l.append(lv[keep].reset_index(drop=True))
        cnt = pd.DataFrame({"l": l, "p": p, "veto": vetoed}).groupby("l").agg(
            candidates=("p", "size"), vetoed=("veto", "sum"))
        summ.append(cnt)
    cols_s = None
    S = pd.concat(kept_s, ignore_index=True) if kept_s else pd.DataFrame()
    L = pd.concat(kept_l, ignore_index=True) if kept_l else pd.DataFrame()
    E = pd.concat(summ) if summ else pd.DataFrame(columns=["candidates", "vetoed"])
    keys = np.concatenate(all_keys) if all_keys else np.array([], np.int64)
    diag = {"hist": hist, "scored": n_scored, "rule_counts": dict(rule_counts), "report": plan.report,
            "keys": keys}
    log(f"  {part}: {n_scored:,} pairs scored, {len(S):,} kept")
    return S, L, E, diag


def business_anchors(S, cfg):
    if not len(S):
        return np.array([], np.int64)
    m = (S["basis"] == "identifier") & (S["p"] >= cfg.core.coparty_min_p) & (S["veto"] == "")
    return np.unique(S.loc[m, "l"].to_numpy().astype(np.int64) * np.int64(1 << 32) + S.loc[m, "r"].to_numpy())


def score_all(pr, params_out, prior, cfg, log=print):
    res = {}
    Sb, Lb, Eb, Db = score_part(pr, "business", params_out["weights"]["business"], prior, cfg, log=log)
    anchors = business_anchors(Sb, cfg)
    log(f"  co-party anchors (business links on an identifier, p >= {cfg.core.coparty_min_p}): {len(anchors)}")
    Sp, Lp, Ep, Dp = score_part(pr, "person", params_out["weights"]["person"], prior, cfg, anchors=anchors, log=log)
    res["business"] = (Sb, Lb, Eb, Db)
    res["person"] = (Sp, Lp, Ep, Dp)
    return res

# %% [markdown]
# ## 13 · Roll-up
#
# **Entities**: one row per extracted party (record_id + part). Its probability is its single
# best (non-vetoed) match; every other kept candidate is listed. `rests_on_name` is true when
# the best match's basis is contextual or name_only: a filter, never a threshold. An extracted
# party with no candidate is shown as such ("no candidate proposed"), not dropped.
#
# **Claims**: per claim, rows, parties, the highest p and its entity, counts by basis x p band,
# and name-only matches at p >= 0.5.
#
# **Where Splink would do better.** Splink clusters pairwise predictions into entities
# (connected components at a threshold); here the unit is one extracted party against the list,
# so the roll-up is a best-match choice with the others listed, per DESIGN.md.

# %%


def pair_table(pr, part, S):
    """Kept pairs with identities, names and the ranking reason."""
    if not len(S):
        return pd.DataFrame()
    X, W = pr.X[part], pr.W[part]
    l, r = S["l"].to_numpy(), S["r"].to_numpy()
    out = pd.DataFrame({
        "pair_id": X["party_id"].to_numpy()[l] + "~" + W["party_id"].to_numpy()[r],
        "extracted_record_id": X["record_id"].to_numpy()[l], "part": part,
        "claim_id": X["claim_id"].to_numpy()[l], "extracted_name": X["display_name"].to_numpy()[l],
        "watchlist_record_id": W["record_id"].to_numpy()[r], "watchlist_name": W["display_name"].to_numpy()[r],
        "p": S["p"].to_numpy(), "bits": S["bits"].to_numpy(), "prior_bits": S["prior_logit"].to_numpy(),
        "basis": S["basis"].to_numpy(), "rests_on_name": np.isin(S["basis"].to_numpy(), ["contextual", "name_only"]),
        "veto": S["veto"].to_numpy(), "rank": S["rank"].to_numpy(), "proposed_by": S["rules"].to_numpy(),
        "_l": l, "_r": r})
    for f in PART_FIELDS[part]:
        out[f"bits_{f}"] = S[f"bits_{f}"].to_numpy()
    return out


def rollup_entities(pr, pairs, E_by_part, cfg):
    ent = []
    for part in ("person", "business"):
        X = pr.X[part]
        E = E_by_part[part]
        base = pd.DataFrame({
            "party_id": X["party_id"], "record_id": X["record_id"], "part": part, "claim_id": X["claim_id"],
            "note_id": X["note_id"], "name": X["display_name"],
            "category_given": X["category_given"], "category_inferred": X["category_inferred"],
            "category_rule": X["category_rule"], "category_used": X["category"],
            "category_mismatch": X["category_mismatch"], "prior_group": X["prior_group"]})
        base["candidates"] = E["candidates"].reindex(np.arange(len(X))).fillna(0).astype(int).to_numpy() if len(E) else 0
        base["vetoed_candidates"] = E["vetoed"].reindex(np.arange(len(X))).fillna(0).astype(int).to_numpy() if len(E) else 0
        P = pairs[pairs["part"] == part] if len(pairs) else pd.DataFrame()
        if len(P):
            ok = P[P["veto"] == ""].sort_values(["_l", "p", "bits", "watchlist_record_id"],
                                                ascending=[True, False, False, True], kind="stable")
            best = ok.groupby("_l").head(1).set_index("_l")
            non_name = ok[~ok["rests_on_name"] & (ok["basis"] != "none")].groupby("_l")["p"].max()
            pos = ok.groupby("_l").cumcount().to_numpy()
            sub = ok[(pos >= 1) & (pos <= cfg.top_k)]
            txt = (sub["watchlist_record_id"] + " (" + sub["p"].map(lambda v: f"{v:.3g}") + ", " + sub["basis"] + ")")
            others = txt.groupby(sub["_l"].to_numpy()).agg("; ".join)
            idx = np.arange(len(X))
            base["best_watchlist_record_id"] = best["watchlist_record_id"].reindex(idx).fillna("").to_numpy()
            base["best_watchlist_name"] = best["watchlist_name"].reindex(idx).fillna("").to_numpy()
            base["p"] = best["p"].reindex(idx).fillna(0.0).to_numpy()
            base["basis"] = best["basis"].reindex(idx).fillna("none").to_numpy()
            base["best_non_name_p"] = non_name.reindex(idx).fillna(0.0).to_numpy()
            base["other_candidates"] = others.reindex(idx).fillna("").to_numpy()
        else:
            base["best_watchlist_record_id"] = ""; base["best_watchlist_name"] = ""
            base["p"] = 0.0; base["basis"] = "none"; base["best_non_name_p"] = 0.0; base["other_candidates"] = ""
        base["rests_on_name"] = np.isin(base["basis"].to_numpy(), ["contextual", "name_only"])
        base["status"] = np.where(base["candidates"] == 0, "no candidate proposed",
                                  np.where(base["best_watchlist_record_id"] == "", "only vetoed candidates", "scored"))
        ent.append(base)
    return pd.concat(ent, ignore_index=True)


def p_band(p):
    return np.select([p >= 0.9, p >= 0.8, p >= 0.5, p >= 0.1], ["p>=0.9", "0.8-0.9", "0.5-0.8", "0.1-0.5"], "p<0.1")


def rollup_claims(entities, xrows_claims):
    e = entities.copy()
    e["band"] = p_band(e["p"].to_numpy())
    g = e.groupby("claim_id", sort=True)
    top = e.sort_values(["claim_id", "p"], ascending=[True, False], kind="stable").groupby("claim_id").head(1).set_index("claim_id")
    out = pd.DataFrame({"rows": xrows_claims.reindex(g.size().index).fillna(0).astype(int),
                        "parties": g.size(), "max_p": g["p"].max()})
    out["max_p_entity"] = top["party_id"].reindex(out.index)
    out["max_p_name"] = top["name"].reindex(out.index)
    out["max_p_basis"] = top["basis"].reindex(out.index)
    ct = pd.crosstab(e["claim_id"], e["basis"] + " " + e["band"])
    out = out.join(ct, how="left").fillna(0)
    out["name_only_at_p_0.5"] = e[(e["basis"] == "name_only") & (e["p"] >= 0.5)].groupby("claim_id").size().reindex(out.index).fillna(0).astype(int)
    return out.reset_index().rename(columns={"index": "claim_id"})

# %% [markdown]
# ## 14 · Evidence
#
# One row per kept pair and compared field that is not empty: both values as normalized,
# the level, m with its source chain and pair count, the u actually used (value-specific or
# field-level) with its source and count, and the bits. A pair's rows sum to its total bits
# (checked in the self-tests); the prior is on the candidate row.
#
# **Where Splink would do better.** Splink's waterfall chart shows the same breakdown
# graphically, per pair, in the browser; this is its table form, filterable in Excel.

# %%
DISPLAY = {"name": lambda F: (F["first"] + " " + F["last"]).str.strip(), "middle": lambda F: F["middle"],
           "org": lambda F: F["org_aliases"].str.replace("|", " / ", regex=False), "dob": lambda F: F["dob"],
           "address": lambda F: F["raw_address"], "phone": lambda F: (F["phone_own"] + " " + F["phone_row"]).str.strip(),
           "spec_cat": lambda F: (F["specialty"] + " / " + F["category"]).str.strip(" /"),
           "co_party": lambda F: F["tie"]}


def evidence_for(pr, part, pairs_part, levels_part, S_part, weights):
    X, W = pr.X[part], pr.W[part]
    l, r = S_part["l"].to_numpy(), S_part["r"].to_numpy()
    vl, vr = {}, {}
    for f in PART_FIELDS[part]:
        if f in DISPLAY:
            vl[f] = DISPLAY[f](X).to_numpy(dtype=object)[l]
            vr[f] = DISPLAY[f](W).to_numpy(dtype=object)[r]
        elif f"id_{f}" in X:
            vl[f] = X[f"id_{f}"].to_numpy(dtype=object)[l]
            vr[f] = W[f"id_{f}"].to_numpy(dtype=object)[r]
    return evidence_rows(pairs_part["pair_id"].to_numpy(), levels_part, S_part, part, weights, vl, vr)


def sensitivity(entities_best, prior_df, cfg):
    """How many entities cross 0.5 / 0.8 / 0.9 if the prior or the recall behind it moved."""
    rows = []
    for _, pr_ in prior_df.iterrows():
        sub = entities_best[(entities_best["part"] == pr_["part"]) & (entities_best["prior_group"] == pr_["group"])]
        bits = sub["bits"].to_numpy()
        for mult in cfg.sensitivity_prior_mult:
            for rmult in cfg.sensitivity_recall:
                rec = min(1.0, pr_["recall"] * rmult) if pr_["recall"] > 0 else 0.0
                base = pr_["prior"] * mult * (pr_["recall"] / rec if rec > 0 else 1.0)
                base = min(base, 0.5)
                logit = math.log2(base / (1 - base)) + bits
                p = 1 / (1 + np.exp2(-logit))
                row = {"part": pr_["part"], "group": pr_["group"], "prior_multiplier": mult,
                       "recall_multiplier": rmult, "prior": base, "entities": len(sub)}
                for t in cfg.p_bands:
                    row[f"entities_p>={t}"] = int((p >= t).sum())
                rows.append(row)
    return pd.DataFrame(rows)
