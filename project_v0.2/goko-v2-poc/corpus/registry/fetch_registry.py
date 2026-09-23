"""Look up the court corpus's named defendants in two public registries.

    python fetch_registry.py

NPPES (CMS provider registry, live API): who holds an NPI under each name,
where, and which person is the authorized official of each organization.
OIG LEIE (federal health-care exclusion list, full CSV): who is excluded.

These lookups are the identifiers the court text lacks. They are evidence
for evaluating the linker, not input to it: nothing here is fed into the
notebook, and a registry hit on a name is itself a name-only match until
something else (NPI, address, official) corroborates it.

Outputs (committed): nppes_lookup.json, leie_hits.json.
Raw LEIE download goes to raw/ (gitignored, ~15 MB).
"""
import csv, io, json, time, urllib.parse, urllib.request
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


def main():
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


if __name__ == "__main__":
    main()
