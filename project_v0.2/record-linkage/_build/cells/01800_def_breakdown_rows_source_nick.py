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