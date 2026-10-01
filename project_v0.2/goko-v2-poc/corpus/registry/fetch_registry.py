"""Public registries: NPPES lookups for evaluation, and the OIG LEIE watchlist table.

    python fetch_registry.py              # download LEIE, rebuild everything below
    python fetch_registry.py --leie-table # rebuild leie_records.csv.gz from raw/ only

NPPES (CMS provider registry, live API): who holds an NPI under each name,
where, and which person is the authorized official of each organization.
OIG LEIE (federal health-care exclusion list, full CSV): who is excluded.

Two different uses, kept apart:

- nppes_lookup.json and leie_hits.json are lookups of the court corpus's named
  defendants. They are evidence for evaluating the linker, not input to it.
- leie_records.csv.gz is the whole exclusion list, reduced to the fields the
  notebook links against (cell 18c, "Flagged for review"). It is a runtime input,
  like the name-frequency tables, and never a label: every match against it is a
  scored link with its own basis, and most rest on a name alone.

Outputs (committed): nppes_lookup.json, leie_hits.json, leie_records.csv.gz.
Raw LEIE download goes to raw/ (gitignored, ~15 MB).
"""
import csv, gzip, hashlib, io, json, sys, time, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "oko0-research/0.1"}
LEIE_URL = "https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv"

PEOPLE = {
    "William A. Weiner, D.O.": ("WILLIAM", "WEINER"),
    "Marvin Moy, M.D.": ("MARVIN", "MOY"),
    "Bradley Pierre": ("BRADLEY", "PIERRE"),
}
ORGS = {
    "Rutland Medical P.C.": "RUTLAND MEDICAL",
    "Nexray Medical Imaging, P.C.": "NEXRAY",
    "Soul Radiology Medical Imaging": "SOUL RADIOLOGY",
}


def nppes(params):
    url = "https://npiregistry.cms.hhs.gov/api/?" + urllib.parse.urlencode({"version": "2.1", "limit": 50, **params})
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        results = json.loads(r.read()).get("results", [])
    rows = []
    for r in results:
        b = r.get("basic", {})
        loc = next((a for a in r.get("addresses", []) if a.get("address_purpose") == "LOCATION"), {})
        tax = next((t for t in r.get("taxonomies", []) if t.get("primary")), {})
        rows.append({
            "npi": r.get("number"), "type": r.get("enumeration_type"),
            "name": b.get("organization_name") or " ".join(x for x in (b.get("first_name"), b.get("middle_name"), b.get("last_name")) if x),
            "credential": b.get("credential"), "status": b.get("status"),
            "enumeration_date": b.get("enumeration_date"), "last_updated": b.get("last_updated"),
            "deactivated": b.get("deactivation_date"),
            "address": ", ".join(x for x in (loc.get("address_1"), loc.get("address_2"), loc.get("city"), loc.get("state"), (loc.get("postal_code") or "")[:5]) if x),
            "phone": loc.get("telephone_number"), "taxonomy": tax.get("desc"),
            "authorized_official": " ".join(x for x in (b.get("authorized_official_first_name"), b.get("authorized_official_last_name")) if x) or None,
        })
    return rows


# The columns the watchlist needs. Street address, ZIP and date of birth stay out of the
# committed table: the linker compares city and state, and nothing here needs more.
LEIE_COLUMNS = ["record_id", "last", "first", "middle", "business", "general", "specialty",
                "npi", "city", "state", "excl_type", "excl_date"]


def _iso(d):
    d = (d or "").strip()
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 and d.strip("0") else ""


def build_leie_records(raw=None, out=None):
    """raw/LEIE_UPDATED.csv -> leie_records.csv.gz, one row per exclusion record.

    record_id is a hash of the record's own identifying fields, so it stays the same
    across refreshes as long as the record does. An NPI of all zeros means "none"."""
    raw = Path(raw or HERE / "raw" / "LEIE_UPDATED.csv")
    out = Path(out or HERE / "leie_records.csv.gz")
    rows = list(csv.DictReader(io.StringIO(raw.read_text(encoding="utf-8", errors="replace"))))
    seen, table = {}, []
    for r in rows:
        key = "|".join((r.get(k) or "").strip().upper() for k in
                       ("LASTNAME", "FIRSTNAME", "MIDNAME", "BUSNAME", "NPI", "CITY", "STATE",
                        "EXCLTYPE", "EXCLDATE", "GENERAL", "SPECIALTY"))
        rid = "leie:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        seen[rid] = seen.get(rid, 0) + 1
        if seen[rid] > 1:                      # an exact duplicate row: keep it, distinctly
            rid = f"{rid}-{seen[rid]}"
        npi = (r.get("NPI") or "").strip()
        table.append([rid, r["LASTNAME"].strip(), r["FIRSTNAME"].strip(), r["MIDNAME"].strip(),
                      r["BUSNAME"].strip(), r["GENERAL"].strip(), r["SPECIALTY"].strip(),
                      npi if npi.strip("0") else "", r["CITY"].strip(), r["STATE"].strip(),
                      r["EXCLTYPE"].strip(), _iso(r["EXCLDATE"])])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(LEIE_COLUMNS)
    w.writerows(table)
    # mtime=0 keeps the file byte-identical when the list has not changed
    with open(out, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    print(f"LEIE table: {len(table):,} records -> {out.name} "
          f"({out.stat().st_size / 1e6:.1f} MB, {sum(1 for t in table if t[7]):,} with NPI)")
    return len(table)


def main():
    if "--leie-table" in sys.argv:
        build_leie_records()
        return
    out = {}
    for label, (first, last) in PEOPLE.items():
        out[label] = nppes({"first_name": first, "last_name": last}); time.sleep(0.5)
    for label, prefix in ORGS.items():
        out[label] = nppes({"organization_name": prefix + "*"}); time.sleep(0.5)
    (HERE / "nppes_lookup.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for label, rows in out.items():
        print(f"NPPES {label}: {len(rows)}")

    raw = HERE / "raw" / "LEIE_UPDATED.csv"
    raw.parent.mkdir(exist_ok=True)
    raw.write_bytes(urllib.request.urlopen(urllib.request.Request(LEIE_URL, headers=UA), timeout=180).read())
    leie = list(csv.DictReader(io.StringIO(raw.read_text(encoding="utf-8", errors="replace"))))
    keep = ("LASTNAME", "FIRSTNAME", "MIDNAME", "BUSNAME", "GENERAL", "SPECIALTY", "NPI",
            "CITY", "STATE", "EXCLTYPE", "EXCLDATE")
    hits = {"source": LEIE_URL, "fetched": time.strftime("%Y-%m-%d"), "rows": len(leie),
            "rows_with_npi": sum(1 for r in leie if (r.get("NPI") or "0").strip("0")), "hits": {}}
    for label, (first, last) in PEOPLE.items():
        hits["hits"][label] = [{k: r[k] for k in keep} for r in leie
                               if r["LASTNAME"] == last and r["FIRSTNAME"] == first]
    for label, prefix in ORGS.items():
        hits["hits"][label] = [{k: r[k] for k in keep} for r in leie if prefix in (r.get("BUSNAME") or "")]
    (HERE / "leie_hits.json").write_text(json.dumps(hits, indent=1) + "\n", encoding="utf-8")
    print(f"LEIE: {hits['rows']:,} rows, {hits['rows_with_npi']:,} with NPI")
    for label, h in hits["hits"].items():
        print(f"LEIE {label}: {len(h)}")
    build_leie_records(raw)


if __name__ == "__main__":
    main()
