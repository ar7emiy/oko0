# ---- Matching core v1.1: scoring, vetoes, basis, co-party, evidence -------------------------


def _lookup_table(w, f, col):
    sub = w[w["field"] == f].sort_values("level_code")
    return sub[col].to_numpy(dtype=float)


def used_u(levels, f, weights):
    """The u each pair's level of field f is scored with: value-specific where the level has
    one, field-level otherwise; for a pooled entity that offered k distinct values of the field
    (column k_<f>), an agreement level's u is multiplied by k (the chance that any of k values
    agrees by chance is at most k u)."""
    n = len(levels)
    lv = levels[f].to_numpy().astype(np.int64)
    ut = _lookup_table(weights, f, "u")
    vspec = np.array([bool(value_specific(f, lev)) for lev in FIELD_LEVELS[f]])
    agree = np.array([lev in AGREEMENT_LEVELS.get(f, set()) for lev in FIELD_LEVELS[f]])
    idx = np.where(lv >= 0, lv, 0)
    uv = levels[f"uv_{f}"].to_numpy(dtype=float) if f"uv_{f}" in levels else np.full(n, np.nan)
    use_v = vspec[idx] & ~np.isnan(uv)
    u = np.where(use_v, uv, ut[idx])
    if f"k_{f}" in levels:
        k = np.maximum(levels[f"k_{f}"].to_numpy(dtype=float), 1.0)
        u = np.where(agree[idx], u * k, u)
    return np.clip(u, 1e-15, 1.0), use_v


def score_pairs(levels, part, weights, prior_logit, params=None):
    """Fellegi-Sunter in bits. For each field: log2(m / u), where u is the value-specific u on
    levels that have one and the field-level u otherwise (times k for a pooled entity); a null
    (empty) field is 0 bits; an agreement level never goes below 0 and a disagreement level
    never above 0; no field outside [bits_min, bits_max]; levels declared 'no evidence' are 0.
    Vetoes set p = 0 and stay visible. Returns a DataFrame: bits_<field>, bits, logit, p, veto,
    basis."""
    params = params or CoreParams()
    n = len(levels)
    out = pd.DataFrame(index=levels.index)
    total = np.zeros(n)
    for f in PART_FIELDS[part]:
        if f not in levels:
            out[f"bits_{f}"] = 0.0
            continue
        lv = levels[f].to_numpy().astype(np.int64)
        mt = _lookup_table(weights, f, "m")
        agree = np.array([lev in AGREEMENT_LEVELS.get(f, set()) for lev in FIELD_LEVELS[f]])
        zero = np.array([lev in ZERO_LEVELS.get(f, set()) for lev in FIELD_LEVELS[f]])
        idx = np.where(lv >= 0, lv, 0)
        u, _ = used_u(levels, f, weights)
        bits = np.clip(np.log2(np.clip(mt[idx], 1e-15, 1.0) / u), params.bits_min, params.bits_max)
        disagree = np.array([lev in DISAGREEMENT_LEVELS.get(f, set()) for lev in FIELD_LEVELS[f]])
        bits = np.where(agree[idx], np.maximum(bits, 0.0), bits)
        bits = np.where(disagree[idx], np.minimum(bits, 0.0), bits)
        bits = np.where(zero[idx] | (lv < 0), 0.0, bits)
        out[f"bits_{f}"] = bits
        total += bits
    veto = np.full(n, "", dtype=object)
    for f in VETO_FIELDS:
        c = f"veto_{f}"
        if c in levels:
            v = levels[c].to_numpy(dtype=bool)
            veto = np.where(v, np.where(veto == "", f, veto + "+" + f), veto)
    out["bits"] = total
    out["logit"] = np.asarray(prior_logit, dtype=float) + total
    p = 1.0 / (1.0 + np.exp2(-np.clip(out["logit"].to_numpy(), -1000, 1000)))
    out["p"] = np.where(veto != "", 0.0, p)
    out["veto"] = veto
    out["basis"] = basis_of(levels, out, part)
    return out


def basis_of(levels, bits, part):
    """What the probability rests on, never upgraded by the score:
    identifier > address > dob > co_party > contextual (name + location/specialty/category)
    > name_only > none."""
    n = len(bits)
    pos = lambda f: (bits[f"bits_{f}"].to_numpy() > 0) if f"bits_{f}" in bits else np.zeros(n, bool)
    lv = lambda f: levels[f].to_numpy() if f in levels else np.full(n, EMPTY)
    ident = np.zeros(n, bool)
    for f in IDENTIFIER_FIELDS:
        if f in PART_FIELDS[part] and f in levels:
            exact = lv(f) == 0        # phone: only an owned, single-holder number
            ident |= exact & pos(f)
    addr = pos("address") & np.isin(lv("address"), [0, 1])
    location = pos("address") & np.isin(lv("address"), [2, 3, 4])
    dob = pos("dob") & np.isin(lv("dob"), [0, 1]) if part == "person" else np.zeros(n, bool)
    cop = pos("co_party")
    name = pos("name") | pos("org")
    context = name & (location | pos("spec_cat"))
    return np.select([ident, addr, dob & name, cop & name, context, name],
                     ["identifier", "address", "dob", "co_party", "contextual", "name_only"],
                     default="none").astype(object)


def apply_coparty(levels, scored, weights, prior_logit, anchored, params=None):
    """One-way co-party evidence for person pairs. `anchored`: boolean array, True where the
    two persons' tied businesses are linked on an identifier (p >= coparty_min_p, no veto),
    decided on business scores alone. Bits are added only where the names already agree, so
    a co-party can strengthen a name but never make one, and name-only links never vouch for
    each other. Returns re-scored pairs."""
    lev = levels.copy()
    has_tie = lev["co_party"].to_numpy() >= 0 if "co_party" in lev else np.zeros(len(lev), bool)
    name_agrees = scored["bits_name"].to_numpy() > 0
    code = np.where(has_tie, 1, EMPTY)
    code = np.where(has_tie & anchored & name_agrees, 0, code)
    lev["co_party"] = code.astype(np.int8)
    lev["uv_co_party"] = np.nan
    return lev, score_pairs(lev, "person", weights, prior_logit, params)


EVIDENCE_COLUMNS = ["pair_id", "field", "value_extracted", "value_watchlist", "level", "m", "m_source",
                    "m_pairs", "u", "u_source", "u_pairs", "values_offered", "bits", "veto"]


def evidence_rows(pair_ids, levels, scored, part, weights, values_l, values_r):
    """Long evidence: one row per pair and non-empty field (plus vetoing fields), with both
    values, the level, m and u with their sources and pair counts, how many distinct values
    a pooled entity offered for the field, and the bits. The rows of a pair sum to its total
    bits (the self-tests check it)."""
    rows = []
    w = weights.set_index(["field", "level_code"])
    for f in PART_FIELDS[part]:
        if f not in levels:
            continue
        lv = levels[f].to_numpy()
        keep = lv >= 0
        if not keep.any():
            continue
        idx = np.flatnonzero(keep)
        codes = lv[idx]
        sub = w.loc[[(f, int(c)) for c in codes]]
        u_all, use_v = used_u(levels, f, weights)
        k = levels[f"k_{f}"].to_numpy()[idx] if f"k_{f}" in levels else np.ones(len(idx))
        rows.append(pd.DataFrame({
            "pair_id": np.asarray(pair_ids)[idx], "field": f,
            "value_extracted": values_l.get(f, np.full(len(lv), ""))[idx] if f in values_l else "",
            "value_watchlist": values_r.get(f, np.full(len(lv), ""))[idx] if f in values_r else "",
            "level": [FIELD_LEVELS[f][c] for c in codes],
            "m": sub["m"].to_numpy(), "m_source": sub["m_source"].to_numpy(),
            "m_pairs": sub["m_pairs"].to_numpy(),
            "u": u_all[idx],
            "u_source": np.where(use_v[idx], sub["u_value_specific"].to_numpy(), sub["u_source"].to_numpy()),
            "u_pairs": sub["u_pairs"].to_numpy(),
            "values_offered": k,
            "bits": scored[f"bits_{f}"].to_numpy()[idx],
            "veto": levels[f"veto_{f}"].to_numpy()[idx] if f"veto_{f}" in levels else False,
        }))
    if not rows:
        return pd.DataFrame(columns=EVIDENCE_COLUMNS)
    ev = pd.concat(rows, ignore_index=True)
    return ev.sort_values(["pair_id", "field"], kind="stable").reset_index(drop=True)