"""Build the outside name-frequency tables the linker uses for rarity.

    python fetch_reference.py            # all three
    python fetch_reference.py census ssa # a subset

Rarity comes only from these outside references, never from the corpus
being linked: a corpus of fraud claims over-represents exactly the names
we are trying to judge, so counting inside it would call a ring member
"common" because the ring is in the data.

Sources (public, no key):
  census  2010 Census surname table: count of people per surname.
  ssa     SSA baby names, births 1930-2005 summed across sexes: a proxy
          for how common a first name is among today's adults.
  nppes   CMS NPPES full monthly file: for every organization provider,
          which name tokens its legal business name uses. Document
          frequency, so "MEDICAL" is common and "NEXRAY" is not.

Outputs (committed, small):  surnames.csv.gz, first_names.csv.gz,
org_tokens.csv.gz, reference_meta.json.
Raw downloads go to raw/ and are gitignored (the NPPES zip is ~1 GB).
"""
import csv, gzip, io, json, re, sys, time, urllib.request, zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36", "Accept": "*/*",
      "Accept-Language": "en-US,en;q=0.9"}   # ssa.gov answers 403 without it

CENSUS_URL = "https://www2.census.gov/topics/genealogy/2010surnames/names.zip"
SSA_URL = "https://www.ssa.gov/oact/babynames/names.zip"
NPPES_INDEX = "https://download.cms.gov/nppes/NPI_Files.html"
SSA_YEARS = range(1930, 2006)
ORG_MIN_DF = 2      # tokens seen once are mostly typos; unseen tokens get df=1 at lookup


def download(url, dest):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  downloading {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0); done = 0; last = time.time()
        while chunk := r.read(1 << 20):
            f.write(chunk); done += len(chunk)
            if time.time() - last > 15:
                print(f"    {done / 1e6:.0f} / {total / 1e6:.0f} MB", flush=True); last = time.time()
    tmp.replace(dest)
    return dest


def write_table(name, header, rows):
    path = HERE / name
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    print(f"  wrote {name} ({len(rows):,} rows, {path.stat().st_size / 1e3:.0f} kB)")


def census():
    z = zipfile.ZipFile(download(CENSUS_URL, RAW / "census2010_names.zip"))
    member = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    rows = []
    with z.open(member) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
            name = r["name"].strip().upper()
            if name and name != "ALL OTHER NAMES":
                rows.append((name, int(r["count"])))
    rows.sort(key=lambda x: -x[1])
    write_table("surnames.csv.gz", ["name", "count"], rows)
    return {"source": CENSUS_URL, "names": len(rows), "people": sum(c for _, c in rows)}


def ssa():
    z = zipfile.ZipFile(download(SSA_URL, RAW / "ssa_names.zip"))
    counts = Counter()
    for y in SSA_YEARS:
        with z.open(f"yob{y}.txt") as f:
            for line in io.TextIOWrapper(f, encoding="latin-1"):
                name, _sex, n = line.strip().split(",")
                counts[name.upper()] += int(n)
    rows = counts.most_common()
    write_table("first_names.csv.gz", ["name", "count"], rows)
    return {"source": SSA_URL, "years": f"{SSA_YEARS.start}-{SSA_YEARS.stop - 1}",
            "names": len(rows), "births": sum(counts.values())}


ORG_TOKEN = re.compile(r"[A-Z0-9]+")


def org_tokens(name):
    return {t for t in ORG_TOKEN.findall(name.upper().replace("'", "")) if len(t) >= 2 and not t.isdigit()}


def nppes():
    page = urllib.request.urlopen(urllib.request.Request(NPPES_INDEX, headers=UA), timeout=60).read().decode("utf-8", "replace")
    monthly = [h for h in re.findall(r"""href=["']([^"']+\.zip)""", page)
               if "Dissemination" in h and "Weekly" not in h and "Deactivated" not in h]
    if not monthly:
        sys.exit("no monthly NPPES file linked from " + NPPES_INDEX)
    url = urllib.parse.urljoin(NPPES_INDEX, monthly[0])
    z = zipfile.ZipFile(download(url, RAW / Path(url).name))
    member = next(n for n in z.namelist()
                  if re.match(r"npidata_pfile_\d+-\d+\.csv$", Path(n).name))
    print(f"  scanning {member}")
    df = Counter(); orgs = 0; seen = 0; t0 = time.time()
    with z.open(member) as f:
        rd = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
        head = next(rd)
        i_type = head.index("Entity Type Code")
        i_org = head.index("Provider Organization Name (Legal Business Name)")
        for row in rd:
            seen += 1
            if row[i_type] == "2" and row[i_org]:
                orgs += 1
                df.update(org_tokens(row[i_org]))
            if seen % 1_000_000 == 0:
                print(f"    {seen / 1e6:.0f}M rows, {orgs:,} orgs, {time.time() - t0:.0f}s", flush=True)
    rows = [(t, n) for t, n in df.most_common() if n >= ORG_MIN_DF]
    write_table("org_tokens.csv.gz", ["token", "df"], rows)
    return {"source": url, "file": member, "providers": seen, "organizations": orgs,
            "tokens": len(rows), "min_df": ORG_MIN_DF}


if __name__ == "__main__":
    import urllib.parse
    want = sys.argv[1:] or ["census", "ssa", "nppes"]
    meta_path = HERE / "reference_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    for name in want:
        print(name)
        meta[name] = {**globals()[name](), "built": time.strftime("%Y-%m-%d")}
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
