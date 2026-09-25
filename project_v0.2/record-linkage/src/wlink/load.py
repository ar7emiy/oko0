# %% [markdown]
# ## 1 · Mappings, reference tables and inputs
#
# **Mappings** (`mappings/*.csv`) are the reviewable tables: column routing, category maps,
# keyword rules, specialty synonyms, the simulation noise table and the published starting
# values of m. **Reference tables** (`reference/`) are copied outside tables, checked against
# the SHA-256 recorded in `reference/SOURCES.md`. **Inputs** are two CSVs with the schema in
# DESIGN.md: `record_id` is required and unique per file, every other column may be empty,
# missing schema columns are added empty, and unknown columns are kept as `x_<name>`
# (displayed, never compared). All-empty columns are reported.
#
# **Where Splink would do better.** Splink reads Parquet or a database table straight into
# DuckDB without a pandas copy, so a 1M-row input costs little memory. Here pandas holds the
# rows as text.

# %%
import csv, gzip, re
from wlink.core import *
from wlink.core import _undot, _DBA_RE, _VIN_MAP, _VIN_W, _words
from wlink.config import *

SCHEMA = ["record_id", "claim_id", "note_id", "category", "first_name", "middle_name",
          "last_name", "dob", "ssn", "driver_license_number", "driver_license_state",
          "provider_npi", "professional_license_number", "professional_license_state",
          "professional_license_type", "provider_specialty", "business_name", "tin", "clinic_npi",
          "street_number", "street_direction", "street_name", "street_type", "unit", "city",
          "state", "zip", "home_phone", "work_phone", "email", "vin", "plate_number", "plate_state"]


class InputError(ValueError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_mappings(mdir):
    """The reviewable tables, validated: known categories only, rates in [0, 1], m per field
    summing to 1."""
    mdir = Path(mdir)
    read = lambda n: pd.read_csv(mdir / n, dtype=str, keep_default_na=False)
    maps = {"columns": read("columns.csv"), "category_map": read("category_map.csv"),
            "category_keywords": read("category_keywords.csv"),
            "specialty_canon": read("specialty_canon.csv"),
            "simulation_noise": read("simulation_noise.csv"), "published_m": read("published_m.csv")}
    cats = {"medical", "legal", "repair shop", "witness", "claimant", "other"}
    for n in ("category_map", "category_keywords"):
        bad = set(maps[n]["category"]) - cats
        if bad:
            raise InputError(f"{n}.csv: unknown categories {sorted(bad)}")
    missing = set(SCHEMA) - set(maps["columns"]["column"])
    if missing:
        raise InputError(f"columns.csv does not route {sorted(missing)}")
    rates = maps["simulation_noise"]["rate"].astype(float)
    if ((rates < 0) | (rates > 1)).any():
        raise InputError("simulation_noise.csv: a rate outside [0, 1]")
    pm = maps["published_m"].assign(m=lambda d: d["m"].astype(float))
    for f, levels in FIELD_LEVELS.items():
        sub = pm[pm["field"] == f]
        if set(sub["level"]) != set(levels):
            raise InputError(f"published_m.csv: field {f} needs levels {levels}")
        if abs(sub["m"].sum() - 1) > 1e-6:
            raise InputError(f"published_m.csv: m for {f} sums to {sub['m'].sum():.4f}, not 1")
    maps["published_m"] = pm
    return maps


def load_reference(rdir, params):
    """Outside tables as plain dicts, plus a hash check against reference/SOURCES.md."""
    rdir = Path(rdir)

    def counts(fname):
        p = rdir / fname
        if not p.exists():
            return None
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            rd = csv.reader(fh); next(rd)
            return {k: int(v) for k, v in rd}

    meta_p = rdir / "reference_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    nick_p = rdir / "nicknames.csv"
    nick = pd.read_csv(nick_p, dtype=str, keep_default_na=False) if nick_p.exists() else None
    recorded = {}
    src = rdir / "SOURCES.md"
    if src.exists():
        for line in src.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\|\s*`([^`]+)`\s*\|.*`([0-9a-f]{64})`\s*\|\s*$", line)
            if m:
                recorded[m.group(1)] = m.group(2)
    checks = []
    for name, want in sorted(recorded.items()):
        p = rdir / name
        got = sha256_file(p) if p.exists() else ""
        checks.append({"file": name, "recorded": want, "actual": got,
                       "status": "ok" if got == want else ("missing" if not got else "CHANGED")})
    return {"surnames": counts("surnames.csv.gz"), "first_names": counts("first_names.csv.gz"),
            "org_tokens": counts("org_tokens.csv.gz"), "meta": meta, "nicknames": nick,
            "hash_checks": pd.DataFrame(checks)}


def load_input(path, source):
    """One input CSV as text. Returns (frame, report)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8")
    df.columns = [c.strip() for c in df.columns]
    return validate_input(df, source)


def validate_input(df, source):
    if "record_id" not in df.columns:
        raise InputError(f"{source}: record_id column is required")
    df = df.copy()
    df["record_id"] = df["record_id"].astype(str).str.strip()
    empty_ids = int((df["record_id"] == "").sum())
    if empty_ids:
        raise InputError(f"{source}: {empty_ids} rows have no record_id")
    dup = df["record_id"][df["record_id"].duplicated(keep=False)]
    if len(dup):
        raise InputError(f"{source}: record_id not unique, e.g. {sorted(set(dup))[:5]}")
    unknown = [c for c in df.columns if c not in SCHEMA]
    df = df.rename(columns={c: (c if c.startswith("x_") else f"x_{c}") for c in unknown})
    added = [c for c in SCHEMA if c not in df.columns]
    for c in added:
        df[c] = ""
    for c in df.columns:
        df[c] = df[c].fillna("").astype(str)
    all_null = [c for c in SCHEMA if c != "record_id" and (df[c].str.strip() == "").all()]
    report = {"source": source, "rows": len(df), "added_columns": added,
              "passthrough_columns": [c for c in df.columns if c.startswith("x_")],
              "all_empty_columns": all_null}
    return df[SCHEMA + [c for c in df.columns if c.startswith("x_")]], report
