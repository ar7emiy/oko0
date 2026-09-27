# ---- Matching core v1.1: value statistics for per-value u and vetoes -----------------------

VALUE_FIELDS = {  # field -> party-frame columns holding its values
    "ssn": ["id_ssn"], "npi": ["id_npi"], "dl": ["id_dl"], "tin": ["id_tin"],
    "license": ["id_license"], "email": ["id_email"], "vin": ["id_vin"], "plate": ["id_plate"],
    "cnpi": ["id_cnpi"], "phone": ["phone_own", "phone_row"],
}
KEY_FIELDS = ["dob", "addr_full", "addr_street", "zip", "city_state", "state", "specialty",
              "category"]


@dataclass
class ValueStats:
    """Per-value counts the comparisons read. `ref_counts[key][value]`: parties of the
    reference (right) population holding the value; `ref_n[key]`: those holding any value.
    `names[field][value]`: distinct names holding an identifier value across both sides.
    `single[field]`: values held under exactly one name."""
    ref_counts: dict
    ref_n: dict
    names: dict
    single: dict


def build_value_stats(left, right):
    """Counts from the two party frames. Identifier u uses how many distinct names hold the
    value across both sides (so a shared or placeholder SSN weighs little); dates, addresses,
    specialty and category use the reference side's own frequencies."""
    ref_counts, ref_n, names, single = {}, {}, {}, {}
    for k in KEY_FIELDS:
        v = right[k][right[k] != ""] if k in right else pd.Series([], dtype=object)
        if k == "category":
            v = v[v != "other"]
        ref_counts[k] = v.value_counts()
        ref_n[k] = int(len(v))
    # v1.1: the reference population's own share of a full person name ("FIRST LAST"), so an
    # exact name's u is never below how often the list itself repeats the name
    if "part" in right and "first" in right:
        pm = (right["part"] == "person") & (right["first"] != "") & (right["last"] != "")
        v = (right.loc[pm, "first"] + " " + right.loc[pm, "last"])
        ref_counts["person_name"] = v.value_counts()
        ref_n["person_name"] = int(len(v))
    both = pd.concat([left, right], ignore_index=True)
    for f, cols in VALUE_FIELDS.items():
        parts = [pd.DataFrame({"v": both[c], "n": both["holder_key"]}) for c in cols if c in both]
        long = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame({"v": [], "n": []})
        long = long[long["v"] != ""]
        nn = long.drop_duplicates().groupby("v")["n"].size()
        names[f] = nn
        single[f] = set(nn.index[nn == 1])
        rv = pd.concat([right[c] for c in cols if c in right], ignore_index=True) if cols else pd.Series([], dtype=object)
        rv = rv[rv != ""]
        ref_n[f] = int((pd.concat([right[c] != "" for c in cols], axis=1).any(axis=1)).sum()) if len(right) else 0
        ref_counts[f] = rv.value_counts()
    return ValueStats(ref_counts, ref_n, names, single)


def junk_values(stats, params):
    """Identifier values held under more names than params.junk_holders: {field: set}."""
    return {f: set(nn.index[nn > params.junk_holders]) for f, nn in stats.names.items()}