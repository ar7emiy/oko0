def value_index(parties, details):
    """(type, value) -> holders per file, distinct names, single-holder and junk flags."""
    d = details.merge(parties[["party_id", "source", "name_key"]], on="party_id", how="left")
    g = d.groupby(["type", "value"], sort=True)
    vi = pd.DataFrame({
        "holders_extracted": g["source"].agg(lambda s: int((s == "X").sum())),
        "holders_watchlist": g["source"].agg(lambda s: int((s == "W").sum())),
        "distinct_names": g["name_key"].nunique(),
        "valid": g["valid"].all(),
        "invalid_reason": g["reason"].agg(lambda s: ",".join(sorted({x for x in s if x}))),
    }).reset_index()
    vi["single_holder"] = vi["valid"] & (vi["distinct_names"] == 1)
    return vi


def value_index_fast(parties, details):
    """Same as value_index, vectorized for large inputs."""
    d = details[["party_id", "type", "value", "valid", "reason"]].merge(
        parties[["party_id", "source", "holder_key"]].rename(columns={"holder_key": "name_key"}), on="party_id", how="left")
    d["is_x"] = (d["source"] == "X").astype(np.int64)
    d["is_w"] = (d["source"] == "W").astype(np.int64)
    g = d.groupby(["type", "value"], sort=True)
    vi = g.agg(holders_extracted=("is_x", "sum"), holders_watchlist=("is_w", "sum"),
               distinct_names=("name_key", "nunique"), valid=("valid", "all")).reset_index()
    bad = d[d["reason"] != ""].groupby(["type", "value"])["reason"].first()
    vi["invalid_reason"] = pd.MultiIndex.from_frame(vi[["type", "value"]]).map(bad.to_dict()).fillna("")
    vi["single_holder"] = vi["valid"] & (vi["distinct_names"] == 1)
    return vi


def mark_junk(vi, params):
    vi = vi.copy()
    many = vi["valid"] & (vi["distinct_names"] > params.junk_holders) & (vi["type"] != "address") & \
        (vi["type"] != "dob")
    vi["junk"] = ~vi["valid"] | many
    vi["junk_reason"] = np.where(~vi["valid"], "invalid:" + vi["invalid_reason"],
                                 np.where(many, "held under " + vi["distinct_names"].astype(str) + " names", ""))
    return vi


def blank_junk(parties, vi):
    """Blank identifier values held under too many names (invalid ones are already blank)."""
    many = vi[vi["junk"] & vi["valid"]]
    col = {"ssn": ["id_ssn"], "npi": ["id_npi"], "dl": ["id_dl"], "license": ["id_license"],
           "tin": ["id_tin"], "cnpi": ["id_cnpi"], "email": ["id_email"], "vin": ["id_vin"],
           "plate": ["id_plate"], "phone": ["phone_own", "phone_row"]}
    n = 0
    for t, cols in col.items():
        bad = set(many.loc[many["type"] == t, "value"])
        if not bad:
            continue
        for c in cols:
            m = parties[c].isin(bad)
            n += int(m.sum())
            parties.loc[m, c] = ""
    return n