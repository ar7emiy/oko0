"""Rebuild the CourtListener test corpus from source.

Two carrier RICO suits against the same set of no-fault medical providers,
brought by different insurers:

    Allstate Insurance Co. v. Pierre           E.D.N.Y. 1:23-cv-06572
    American Transit Insurance Co. v. Pierre   E.D.N.Y. 1:24-cv-00360

Each docket becomes one claim; each court document becomes one note. The text is
the PDF's own text layer, extracted page by page and written unaltered: no
cleaning, no normalisation, no pseudonymisation. Pages are separated by a form
feed (\\f), the same convention pdftotext uses.

    python fetch.py            # needs: pip install pypdf
    python fetch.py --gold-only   # just refresh gold/docket_parties.json

Downloaded PDFs are cached in ./pdf/ (gitignored). Everything else is committed.
"""
import hashlib
import io
import json
import re
import sys
import time
from collections import defaultdict
import urllib.parse
import urllib.request
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
NOTES = HERE / "notes"
PDFS = HERE / "pdf"
UA = {"User-Agent": "oko0-research/0.1 (test corpus; low volume)"}
SEARCH = "https://www.courtlistener.com/api/rest/v4/search/?"
STORAGE = "https://storage.courtlistener.com/"

# claim_id follows the notebook's {client}-{occurrence}-{coverage}-{seq} format:
#   client     one synthetic id per insurer, so the two suits are different clients
#   occurrence the docket number (1:23-cv-06572 -> 236572)
#   coverage   "RI" for RICO
DOCKETS = {
    "1:23-cv-06572": {"docket_id": 67756272, "claim_id": "100001-236572-RI-01",
                      "case": "Allstate Insurance Company v. Pierre", "note_prefix": 71},
    "1:24-cv-00360": {"docket_id": 68168028, "claim_id": "100002-240360-RI-01",
                      "case": "American Transit Insurance Company v. Pierre", "note_prefix": 72},
}

# (docket, document_number, attachment_number, why it is in the corpus)
SELECTION = [
    ("1:23-cv-06572", 36, None, "defendants' answer: denials against the complaint"),
    ("1:23-cv-06572", 45, None, "court's account of the scheme on preliminary injunction"),
    ("1:23-cv-06572", 85, None, "short order: a note with almost nothing in it"),
    ("1:24-cv-00360", 1, None, "complaint: Rule 9(b) particularity, identifier-dense"),
    ("1:24-cv-00360", 40, None, "a defendant's answer to that complaint: same docket, opposite stance"),
    ("1:24-cv-00360", 52, None, "memorandum and order"),
    ("1:24-cv-00360", 77, None, "report and recommendation"),
]


def getj(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.loads(r.read())


def getb(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
        return r.read()


def available_documents(docket_id):
    url = SEARCH + urllib.parse.urlencode({"type": "rd", "q": f"docket_id:{docket_id}",
                                           "available_only": "on"})
    docs = []
    while url:
        d = getj(url)
        docs += [x for x in d["results"] if x.get("is_available")]
        url = d.get("next")
        time.sleep(1)
    return docs


def _party_key(name):
    """Clerk party names, compared loosely: case, punctuation and legal suffixes ignored."""
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    drop = {"p", "c", "pc", "inc", "llc", "d", "o", "m", "md", "do", "the", "a"}
    return " ".join(w for w in s.split() if w not in drop)


def fetch_gold():
    """The clerk's party / attorney / firm lists per docket, saved as evaluation gold.

    Runtime never reads this file (AGENTS.md rule 13). It exists so the pipeline's party
    recall and its cross-claim links can be scored against something it did not produce.
    """
    gold = {"source": "CourtListener v4 search, type=r (docket party lists as entered by the clerk)",
            "fetched": time.strftime("%Y-%m-%d"), "dockets": {}}
    for num, meta in DOCKETS.items():
        d = getj(SEARCH + urllib.parse.urlencode({"type": "r", "q": f"docket_id:{meta['docket_id']}"}))
        r = d["results"][0]
        gold["dockets"][meta["claim_id"]] = {
            "docket": num, "case": r.get("caseName"),
            "parties": r.get("party") or [], "attorneys": r.get("attorney") or [],
            "firms": sorted(set(r.get("firm") or []))}
        time.sleep(1)

    # Parties named on both dockets: the true cross-claim identities. A d/b/a name is one
    # party under two names, so each side of it is a key.
    keys = defaultdict(lambda: defaultdict(set))
    for claim, g in gold["dockets"].items():
        for p in g["parties"]:
            for part in re.split(r"\bd/b/a\b", p, flags=re.I):
                keys[_party_key(part)][claim].add(p)
    shared = {}
    for k, by_claim in keys.items():
        if len(by_claim) > 1:
            names = tuple(sorted({n for ns in by_claim.values() for n in ns}))
            shared[names] = {c: sorted(ns) for c, ns in by_claim.items()}
    gold["cross_claim_identities"] = [{"names": list(n), "by_claim": v} for n, v in sorted(shared.items())]
    out = HERE / "gold" / "docket_parties.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(gold, indent=2) + "\n", encoding="utf-8")
    print(f"gold: {sum(len(g['parties']) for g in gold['dockets'].values())} parties, "
          f"{len(gold['cross_claim_identities'])} named on both dockets -> {out}")
    for x in gold["cross_claim_identities"]:
        print(f"  {x['names']}")


def main():
    fetch_gold()
    NOTES.mkdir(parents=True, exist_ok=True)
    PDFS.mkdir(exist_ok=True)
    catalog = {num: available_documents(meta["docket_id"]) for num, meta in DOCKETS.items()}

    manifest = []
    for num, doc_no, att, why in SELECTION:
        meta = DOCKETS[num]
        doc = next(d for d in catalog[num]
                   if str(d.get("document_number")) == str(doc_no)
                   and (d.get("attachment_number") or None) == att)
        pdf_path = PDFS / Path(doc["filepath_local"]).name
        if not pdf_path.exists():
            pdf_path.write_bytes(getb(STORAGE + doc["filepath_local"]))
            time.sleep(1)
        raw = pdf_path.read_bytes()

        pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages]
        text = "\f".join(pages)
        note_id = f"{meta['note_prefix']}{doc_no:04d}"
        out = NOTES / f"{meta['claim_id']}_{note_id}.txt"
        # newline="" so the text layer's own line endings reach disk untouched
        out.write_text(text, encoding="utf-8", newline="")

        chars_per_page = len(text) / max(len(pages), 1)
        manifest.append({
            "file": f"notes/{out.name}",
            "claim_id": meta["claim_id"], "note_id": int(note_id),
            "case": meta["case"], "docket": num, "court": "E.D.N.Y.",
            "document_number": doc_no, "attachment_number": att,
            "description": (doc.get("description") or doc.get("short_description") or "").strip(),
            "date_filed": doc.get("entry_date_filed"),
            "pages": len(pages), "chars": len(text),
            "chars_per_page": round(chars_per_page),
            # a scanned image with no text layer extracts to almost nothing
            "text_layer": "ok" if chars_per_page > 200 else "SPARSE - likely scanned, needs OCR",
            "why": why,
            "source_pdf": STORAGE + doc["filepath_local"],
            "courtlistener_docket": f"https://www.courtlistener.com/docket/{meta['docket_id']}/",
            "pdf_sha256": hashlib.sha256(raw).hexdigest(),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "extraction": f"pypdf page text layer, pages joined with \\f",
        })
        print(f"{out.name}  pages={len(pages):<4} chars={len(text):<7} "
              f"per_page={round(chars_per_page):<5} {manifest[-1]['text_layer']}")

    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(manifest)} notes, {sum(m['chars'] for m in manifest):,} chars -> {NOTES}")


if __name__ == "__main__":
    fetch_gold() if "--gold-only" in sys.argv else main()
