# %% [markdown]
# ## LEIE exporter
#
# Raw OIG LEIE (`UPDATED.csv`, 84,001 rows) → the input schema. The export keeps DOB and the
# street address, so it lives only in gitignored `data/` (it is personal data about real
# people). Mapping, as decided in PLAN.md open question 3:
#
# | LEIE | Input column |
# |---|---|
# | LASTNAME, FIRSTNAME, MIDNAME | last_name, first_name, middle_name |
# | BUSNAME | business_name |
# | GENERAL | professional_license_type (drives the inferred category) |
# | SPECIALTY | provider_specialty |
# | NPI (all zeros = none) | provider_npi for a person, clinic_npi for a business |
# | DOB (YYYYMMDD) | dob (ISO) |
# | ADDRESS | street_number, street_direction, street_name, street_type, unit (parsed) |
# | CITY, STATE, ZIP | city, state, zip |
# | EXCLTYPE, EXCLDATE, REINDATE, WAIVERDATE, WVRSTATE, UPIN | x_ display columns, never compared |
#
# `record_id` is goko's scheme (a hash of the record's identifying fields), so it is stable
# across refreshes.
#
# **Where Splink would do better.** Not applicable: this is data preparation.

# %%
import csv, io
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *
from wlink.load import *
from wlink.simulate import *
from wlink.synth import make_dataset

LEIE_URL = "https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv"


def _iso8(d):
    d = (d or "").strip()
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 and d.strip("0") else ""


def export_leie(raw_path, out_path=None):
    """Raw LEIE CSV -> input-schema frame (and CSV when out_path is given)."""
    raw = pd.read_csv(raw_path, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8",
                      encoding_errors="replace")
    raw = raw.apply(lambda s: s.str.strip())
    key = raw[["LASTNAME", "FIRSTNAME", "MIDNAME", "BUSNAME", "NPI", "CITY", "STATE", "EXCLTYPE",
               "EXCLDATE", "GENERAL", "SPECIALTY"]].apply(lambda s: s.str.upper()).agg("|".join, axis=1)
    rid = "leie:" + key.map(lambda k: hashlib.sha1(k.encode("utf-8")).hexdigest()[:12])
    n = rid.groupby(rid).cumcount()
    rid = np.where(n > 0, rid + "-" + (n + 1).astype(str), rid)
    person = (raw["LASTNAME"] != "") | (raw["FIRSTNAME"] != "")
    npi = raw["NPI"].where(raw["NPI"].str.strip("0") != "", "")
    parts = raw["ADDRESS"].map(parse_street_line)
    out = pd.DataFrame({c: "" for c in SCHEMA}, index=raw.index)
    out["record_id"] = rid
    out["first_name"], out["middle_name"], out["last_name"] = raw["FIRSTNAME"], raw["MIDNAME"], raw["LASTNAME"]
    out["business_name"] = raw["BUSNAME"]
    out["professional_license_type"] = raw["GENERAL"]
    out["provider_specialty"] = raw["SPECIALTY"]
    out["provider_npi"] = np.where(person, npi, "")
    out["clinic_npi"] = np.where(person, "", npi)
    out["dob"] = raw["DOB"].map(_iso8)
    out["street_number"] = parts.map(lambda t: t[0]); out["street_direction"] = parts.map(lambda t: t[1])
    out["street_name"] = parts.map(lambda t: t[2]); out["street_type"] = parts.map(lambda t: t[3])
    out["unit"] = parts.map(lambda t: t[4])
    out["city"], out["state"], out["zip"] = raw["CITY"], raw["STATE"], raw["ZIP"]
    for c in ("EXCLTYPE", "EXCLDATE", "REINDATE", "WAIVERDATE", "WVRSTATE", "UPIN"):
        out[f"x_{c.lower()}"] = raw[c] if c in raw else ""
    out["x_excldate"] = out["x_excldate"].map(_iso8)
    if out_path:
        out.to_csv(out_path, index=False, encoding="utf-8")
    return out


def leie_test_set(leie_rows, ref, noise, seed, n_copies, n_fictional):
    """Extracted rows for the LEIE run: noisy copies of n_copies LEIE rows (the full,
    pessimistic noise table) plus n_fictional parties not on the list; truth pairs for the
    copies. Copies lose the LEIE-only columns and get claim and note ids."""
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(leie_rows), size=min(n_copies, len(leie_rows)), replace=False))
    src = leie_rows.iloc[pick][SCHEMA].copy()
    fake = Fake(ref, rng)
    copies, log = apply_noise(src, noise, fake, rng, scale=1.0, id_prefix="lx")
    copies["professional_license_type"] = ""       # GENERAL is LEIE's field, not a claim form's
    copies["category"] = np.where(copies["first_name"].str.len() + copies["last_name"].str.len() > 0,
                                  "medical", "")
    fict, _, _, _, _ = make_dataset(n_fictional, n_fictional // 5, 0, ref, noise, seed + 1, x_share=1.0,
                                    w_share=0.0, include_edges=False, prefix="LF")
    fict = fict.iloc[:n_fictional]
    X = pd.concat([copies, fict], ignore_index=True)
    order = rng.permutation(len(X))
    X["claim_id"] = [f"LC{i // 3:06d}" for i in np.argsort(order)]
    X["note_id"] = X["claim_id"] + "-N0"
    person = (src["first_name"] != "") | (src["last_name"] != "")
    truth = pd.DataFrame({"x_record_id": copies["record_id"].to_numpy(),
                          "part": np.where(person.to_numpy(), "person", "business"),
                          "w_record_id": src["record_id"].to_numpy()})
    return X.fillna("").astype(str), truth, log
