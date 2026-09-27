ID_TYPES = ["ssn", "npi", "dl", "license", "tin", "cnpi", "email", "vin", "plate"]


def _norm3(series, func):
    """Apply a (value, valid, reason) normalizer once per distinct value."""
    res = map_unique(series, func)
    return (res.map(lambda t: t[0]), res.map(lambda t: t[1]), res.map(lambda t: t[2]))


def normalize_rows(df, maps, nick, params, source, std=None):
    """Row-level normalized frame (same index as df). `std`: the address standardizer
    (section 2a); None uses the components as given."""
    std = std or AddressStandardizer("given")
    ad = std.standardize(df)
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
    akey = (ad["number"] + "\x1f" + ad["direction"] + "\x1f" + ad["name"] + "\x1f" + ad["type"] + "\x1f"
            + ad["unit"])
    a = map_unique(akey, lambda k: norm_street_parts(*k.split("\x1f")))
    out["addr_number"] = a.map(lambda t: t[0]); out["addr_dir"] = a.map(lambda t: t[1])
    out["addr_name"] = a.map(lambda t: t[2]); out["addr_type"] = a.map(lambda t: t[3])
    out["addr_unit"] = a.map(lambda t: t[4])
    out["city"] = map_unique(ad["city"], norm_city)
    out["state"] = map_unique(ad["state"], norm_state)
    out["zip"] = map_unique(ad["zip"], norm_zip)
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