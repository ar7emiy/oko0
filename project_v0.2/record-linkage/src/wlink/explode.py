# %% [markdown]
# ## 2 · Normalize
#
# Every column is normalized per `mappings/columns.csv` with the core's normalizers, once per
# distinct value (a name that appears 3,000 times is parsed once). Each identifier gets a
# validity flag and a reason: NPI Luhn check, VIN check digit, SSN ranges, EIN prefixes,
# placeholder values such as 000000000, 123456789 or 1900-01-01. Invalid values stay visible in
# the details table and are never compared.
#
# **Where Splink would do better.** Splink leaves cleaning to the user but its comparison
# library normalizes inside SQL, in parallel. Here name and address parsing are Python loops
# over distinct values; at 1.3M rows they are the second-largest cost after comparisons.

# %%
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.load import *

ID_TYPES = ["ssn", "npi", "dl", "license", "tin", "cnpi", "email", "vin", "plate"]


def _norm3(series, func):
    """Apply a (value, valid, reason) normalizer once per distinct value."""
    res = map_unique(series, func)
    return (res.map(lambda t: t[0]), res.map(lambda t: t[1]), res.map(lambda t: t[2]))


def normalize_rows(df, maps, nick, params, source):
    """Row-level normalized frame (same index as df)."""
    out = pd.DataFrame({"record_id": df["record_id"], "source": source,
                        "claim_id": df["claim_id"].str.strip(), "note_id": df["note_id"].str.strip()})
    key = df["first_name"] + "\x1f" + df["middle_name"] + "\x1f" + df["last_name"]
    parts = map_unique(key, lambda k: clean_person(*k.split("\x1f")))
    out["first"] = parts.map(lambda t: t[0])
    out["middle"] = parts.map(lambda t: t[1])
    out["last"] = parts.map(lambda t: t[2])
    out["business_raw"] = df["business_name"].map(fold)
    out["org_aliases"] = map_unique(df["business_name"], org_alias_string)
    out["dob"], out["dob_valid"], out["dob_reason"] = _norm3(df["dob"], lambda v: norm_dob(v, params))
    out["ssn"], out["ssn_valid"], out["ssn_reason"] = _norm3(df["ssn"], norm_ssn)
    out["npi"], out["npi_valid"], out["npi_reason"] = _norm3(df["provider_npi"], norm_npi)
    out["tin"], out["tin_valid"], out["tin_reason"] = _norm3(df["tin"], norm_tin)
    out["cnpi"], out["cnpi_valid"], out["cnpi_reason"] = _norm3(df["clinic_npi"], norm_npi)
    out["email"], out["email_valid"], out["email_reason"] = _norm3(df["email"], norm_email)
    out["vin"], out["vin_valid"], out["vin_reason"] = _norm3(df["vin"], norm_vin)
    q = lambda a, b: map_unique(df[a] + "\x1f" + df[b], lambda k: k.split("\x1f"))
    out["dl"], out["dl_valid"], out["dl_reason"] = _norm3(
        df["driver_license_number"] + "\x1f" + df["driver_license_state"], lambda k: norm_dl(*k.split("\x1f")))
    out["license"], out["license_valid"], out["license_reason"] = _norm3(
        df["professional_license_number"] + "\x1f" + df["professional_license_state"],
        lambda k: norm_license(*k.split("\x1f")))
    out["plate"], out["plate_valid"], out["plate_reason"] = _norm3(
        df["plate_number"] + "\x1f" + df["plate_state"], lambda k: norm_plate(*k.split("\x1f")))
    out["home_phone"], out["home_phone_valid"], out["home_phone_reason"] = _norm3(df["home_phone"], norm_phone)
    out["work_phone"], out["work_phone_valid"], out["work_phone_reason"] = _norm3(df["work_phone"], norm_phone)
    out["license_type"] = df["professional_license_type"].map(fold)
    canon = dict(zip(maps["specialty_canon"]["raw"].map(fold), maps["specialty_canon"]["canonical"].map(fold)))
    out["specialty_raw"] = df["provider_specialty"].map(fold)
    out["specialty"] = out["specialty_raw"].map(lambda s: canon.get(s, s))
    out["category_given"] = df["category"].str.strip().str.lower()
    akey = (df["street_number"] + "\x1f" + df["street_direction"] + "\x1f" + df["street_name"] + "\x1f"
            + df["street_type"] + "\x1f" + df["unit"])
    a = map_unique(akey, lambda k: norm_street_parts(*k.split("\x1f")))
    out["addr_number"] = a.map(lambda t: t[0]); out["addr_dir"] = a.map(lambda t: t[1])
    out["addr_name"] = a.map(lambda t: t[2]); out["addr_type"] = a.map(lambda t: t[3])
    out["addr_unit"] = a.map(lambda t: t[4])
    out["city"] = map_unique(df["city"], norm_city)
    out["state"] = map_unique(df["state"], norm_state)
    out["zip"] = map_unique(df["zip"], norm_zip)
    keys = map_unique(out["addr_number"] + "\x1f" + out["addr_name"] + "\x1f" + out["addr_unit"] + "\x1f"
                      + out["zip"] + "\x1f" + out["city"] + "\x1f" + out["state"],
                      lambda k: address_keys(*k.split("\x1f")))
    out["addr_full"] = keys.map(lambda t: t[0]); out["addr_street"] = keys.map(lambda t: t[1])
    out["city_state"] = keys.map(lambda t: t[3])
    xcols = [c for c in df.columns if c.startswith("x_")]
    for c in xcols:
        out[c] = df[c]
    # raw display values
    out["raw_name"] = (df["first_name"] + " " + df["middle_name"] + " " + df["last_name"]).str.split().str.join(" ")
    out["raw_business"] = df["business_name"].str.strip()
    out["raw_address"] = (df["street_number"] + " " + df["street_direction"] + " " + df["street_name"] + " "
                          + df["street_type"] + " " + df["unit"] + ", " + df["city"] + " " + df["state"]
                          + " " + df["zip"]).str.split().str.join(" ").str.strip(", ")
    return out.reset_index(drop=True)

# %% [markdown]
# ## 3 · Breakdown
#
# Each row yields up to two parties, tied by the row: a **person part** when there is a first
# or last name, and a **business part** when there is a business name, or a TIN or clinic NPI
# with no business name. Details go to their owner per `mappings/columns.csv`: address and work
# phone are held by both parts with ownership `row`; the email goes to the person, or to the
# business when the row has no person. Rows that yield no party are reported, never dropped
# silently.
#
# **Where Splink would do better.** Splink links records, not parts of records; the split is
# ours. What Splink would add is its array comparisons for multi-valued fields (a party with
# several phones), which this schema does not need because a row holds one value per column.

# %%


def breakdown(rows, source, nick):
    """Rows -> (parties, details, ties, empty_rows)."""
    has_person = (rows["first"] != "") | (rows["last"] != "")
    raw_tin_or_cnpi = (rows["tin"] != "") | (rows["cnpi"] != "")
    has_business = (rows["org_aliases"] != "") | raw_tin_or_cnpi
    pi = np.flatnonzero(has_person.to_numpy())
    bi = np.flatnonzero(has_business.to_numpy())
    empty = rows.loc[~(has_person | has_business), ["record_id"]]

    def base(idx, part):
        r = rows.iloc[idx]
        tag = "P" if part == "person" else "B"
        p = pd.DataFrame({"party_id": source + ":" + r["record_id"] + ":" + tag,
                          "source": source, "record_id": r["record_id"].to_numpy(), "part": part,
                          "row": idx, "claim_id": r["claim_id"].to_numpy(),
                          "note_id": r["note_id"].to_numpy()})
        return p

    P = base(pi, "person")
    B = base(bi, "business")
    rp, rb = rows.iloc[pi], rows.iloc[bi]
    for c in ("first", "middle", "last"):
        P[c] = rp[c].to_numpy()
        B[c] = ""
    P["org_aliases"] = ""
    B["org_aliases"] = rb["org_aliases"].to_numpy()
    P["name_key"] = np.where(P["first"] != "", P["first"] + " " + P["last"], P["last"])
    B["name_key"] = [a.split("|")[0] if a else "" for a in B["org_aliases"]]
    # who holds a value: surname + first initial, so 'R. Smith' and 'Robert Smith' are one holder
    P["holder_key"] = P["last"] + "|" + P["first"].str[:1]
    B["holder_key"] = B["name_key"]
    P["display_name"] = rp["raw_name"].to_numpy()
    B["display_name"] = np.where(rb["raw_business"].to_numpy() != "", rb["raw_business"].to_numpy(),
                                 "(no name: " + np.where(rb["tin"].to_numpy() != "", "TIN " + rb["tin"].to_numpy(),
                                                         "clinic NPI " + rb["cnpi"].to_numpy()) + ")")
    P["first_roots"] = map_unique(P["first"], nick.roots_string).to_numpy()
    B["first_roots"] = ""
    P["last_nysiis"] = map_unique(P["last"], nysiis).to_numpy()
    B["last_nysiis"] = ""
    # details owned by the person only
    for c, col in (("dob", "dob"),):
        P[c] = np.where(rp["dob_valid"].to_numpy(dtype=bool), rp["dob"].to_numpy(), "")
        B[c] = ""
    P["dob_int"] = [int(d.replace("-", "")) if d else 0 for d in P["dob"]]
    B["dob_int"] = 0
    valid = lambda r, t: np.where(r[f"{t}_valid"].to_numpy(dtype=bool), r[t].to_numpy(), "")
    for t in ("ssn", "npi", "dl", "license", "vin", "plate"):
        P[f"id_{t}"] = valid(rp, t)
        B[f"id_{t}"] = ""
    for t in ("tin", "cnpi"):
        B[f"id_{t}"] = valid(rb, t)
        P[f"id_{t}"] = ""
    # email: the person's, or the business's when the row has no person
    P["id_email"] = valid(rp, "email")
    B["id_email"] = np.where(has_person.to_numpy()[bi], "", valid(rb, "email"))
    P["phone_own"] = valid(rp, "home_phone")
    B["phone_own"] = ""
    P["phone_row"] = valid(rp, "work_phone")
    B["phone_row"] = valid(rb, "work_phone")
    for c in ("addr_full", "addr_street", "zip", "city_state", "state", "city", "addr_number",
              "addr_name", "addr_unit"):
        P[c] = rp[c].to_numpy()
        B[c] = rb[c].to_numpy()
    P["specialty"] = rp["specialty"].to_numpy()
    B["specialty"] = ""                        # provider_specialty is the person's
    P["specialty_raw_row"] = rp["specialty_raw"].to_numpy()
    B["specialty_raw_row"] = rb["specialty_raw"].to_numpy()   # category inference is row-level
    for c in ("license_type", "category_given", "raw_address"):
        P[c] = rp[c].to_numpy()
        B[c] = rb[c].to_numpy()
    P["business_raw"] = rp["business_raw"].to_numpy()
    B["business_raw"] = rb["business_raw"].to_numpy()
    parties = pd.concat([P, B], ignore_index=True)
    # ties: the other part of the same row
    tie = parties.groupby("row")["party_id"].agg(list)
    other = {}
    for ids in tie:
        if len(ids) == 2:
            other[ids[0]], other[ids[1]] = ids[1], ids[0]
    parties["tie"] = parties["party_id"].map(other).fillna("")
    parties = parties.sort_values(["row", "part"], kind="stable").reset_index(drop=True)
    ties = parties[(parties["part"] == "person") & (parties["tie"] != "")][["record_id", "party_id", "tie"]]
    ties = ties.rename(columns={"party_id": "person_party", "tie": "business_party"}).reset_index(drop=True)
    details = build_details(rows, parties, pi, bi, has_person.to_numpy())
    return parties, details, ties, empty


DETAIL_SPEC = [  # (type, row column, owner, ownership, source column)
    ("dob", "dob", "person", "own", "dob"),
    ("ssn", "ssn", "person", "own", "ssn"),
    ("npi", "npi", "person", "own", "provider_npi"),
    ("dl", "dl", "person", "own", "driver_license_number"),
    ("license", "license", "person", "own", "professional_license_number"),
    ("vin", "vin", "person", "own", "vin"),
    ("plate", "plate", "person", "own", "plate_number"),
    ("phone", "home_phone", "person", "own", "home_phone"),
    ("phone", "work_phone", "both", "row", "work_phone"),
    ("email", "email", "person_else_business", "own", "email"),
    ("tin", "tin", "business", "own", "tin"),
    ("cnpi", "cnpi", "business", "own", "clinic_npi"),
    ("address", "addr_full", "both", "row", "street_number..zip"),
]


def build_details(rows, parties, pi, bi, has_person):
    """Long details table: party, type, normalized value, validity, ownership, source column."""
    pid_p = parties.set_index(["row", "part"])["party_id"]
    person_of = pd.Series(pid_p.xs("person", level="part")) if len(pi) else pd.Series(dtype=object)
    business_of = pd.Series(pid_p.xs("business", level="part")) if len(bi) else pd.Series(dtype=object)
    out = []
    for typ, col, owner, own, src in DETAIL_SPEC:
        vals = rows[col]
        present = vals != ""
        vflag = rows[f"{col}_valid"] if f"{col}_valid" in rows else pd.Series(True, index=rows.index)
        reason = rows[f"{col}_reason"] if f"{col}_reason" in rows else pd.Series("", index=rows.index)
        targets = []
        if owner in ("person", "both", "person_else_business"):
            targets.append(person_of)
        if owner in ("business", "both"):
            targets.append(business_of)
        if owner == "person_else_business":
            targets.append(business_of[~pd.Series(has_person)[business_of.index].to_numpy()])
        for tgt in targets:
            idx = tgt.index[present.to_numpy()[tgt.index]] if len(tgt) else []
            if len(idx) == 0:
                continue
            out.append(pd.DataFrame({"party_id": tgt.loc[idx].to_numpy(), "type": typ,
                                     "value": vals.to_numpy()[idx], "valid": vflag.to_numpy()[idx].astype(bool),
                                     "reason": reason.to_numpy()[idx], "ownership": own,
                                     "source_column": src}))
    if not out:
        return pd.DataFrame(columns=["party_id", "type", "value", "valid", "reason", "ownership", "source_column"])
    return pd.concat(out, ignore_index=True)

# %% [markdown]
# ## 4 · Value index
#
# For every (type, value): how many parties hold it in each file, how many distinct names hold
# it, whether one name holds it (single-holder: the only kind that can veto or anchor), and
# whether it is junk (fails validation, or is held under more than `junk_holders` names). It
# drives shared-identifier counts, anchors, per-value u and the row-level evidence. Junk values
# are blanked from the party frames before any comparison and listed in the manifest.
#
# **Where Splink would do better.** Splink computes term frequencies per column in SQL and
# joins them onto pairs; the idea is the same, and Splink's version is lazier with memory.

# %%


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
