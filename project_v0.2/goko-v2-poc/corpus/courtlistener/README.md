# CourtListener corpus — two carrier RICO suits, one set of defendants

Seven court filings from two federal no-fault insurance fraud suits in the Eastern District
of New York. Two different insurers sued **the same five defendants** over the same alleged
scheme:

| | Allstate v. Pierre | American Transit v. Pierre |
|---|---|---|
| Docket | 1:23-cv-06572 | 1:24-cv-00360 |
| `claim_id` | `100001-236572-RI-01` | `100002-240360-RI-01` |
| Bradley Pierre | ✓ | ✓ |
| William A. Weiner, D.O. | ✓ | ✓ |
| Marvin Moy, M.D. | ✓ | ✓ |
| Rutland Medical P.C. | ✓ | ✓ |
| Nexray Medical Imaging, P.C. | ✓ | ✓ *d/b/a Soul Radiology Medical Imaging* |

That is the case the cross-claim stage exists for: the same parties, under different
surface forms, in claims belonging to **different clients**.

## Mapping

A docket already has real document boundaries, so nothing is split or invented:

| Notebook concept | Source |
|---|---|
| `claim_id` | one per docket; the client segment is one synthetic id per insurer |
| `note_id` | one per filed document: `71` / `72` prefix + document number |
| note text | the PDF's text layer, pages joined with `\f`, **otherwise unaltered** |

`manifest.json` records, for every note: docket, document number, description, filing date,
page count, source PDF URL, and SHA-256 of both the PDF and the extracted text.

| Note | Document | Pages | Why it's here |
|---|---|---|---|
| `710036` | Answer to complaint | 103 | defendants' denials |
| `710045` | Memorandum & order, preliminary injunction | 16 | the court's account of the scheme |
| `710085` | Order dismissing case | 2 | a note with almost nothing in it |
| `720001` | Complaint | 93 | the full allegations |
| `720040` | Answer by Weiner and Nexray | 54 | same docket as the complaint, opposite stance |
| `720052` | Memorandum & order | 12 | |
| `720077` | Report & recommendation | 17 | |

## What it tests, and what it doesn't

**It does test** robustness on text nobody wrote to be parsed:

- Names broken across lines (`WILLIAM A. WEINER, \nD.O.`), runs of spaces (`SOUL   RADIOLOGY`),
  tabs between words (`UNITED\tSTATES`), curly quotes, 1,000+ doubled spaces per filing.
- Words split by the PDF text layer: `inform ation`, `beli ef`, `MEDICA L IMAGING`. A model
  quoting the corrected word will not find it by exact match.
- Defined-term coreference: `Bradley Pierre (“Pierre”)`, `the Answering Defendants`.
- Notes up to 207k characters. The pipeline has no chunking, so this is where whole-note
  extraction meets its limit.
- A complaint and an answer on one docket: the `stance` contrast.

**It does not test** the structured-identifier path. There are **no NPIs, no EINs, no
10-digit identifiers** in any of these filings; the only pattern-lane finds are law-firm
phone numbers in signature blocks. The particulars are presumably in exhibits not included
in the main PDFs. Cross-claim linking in this pipeline is keyed only on shared details, so
expect it to find little here even though the same five defendants are in both suits.

It is also not claim-note register. These are pleadings — formal, long-sentenced — not an
adjuster's shorthand. Nothing public is.

## Names

These are public federal court records and are kept verbatim, including the names of the
parties, because the point of the corpus is unprocessed text. Allegations in a complaint
are allegations; neither case here reached a judgment on the merits in these documents.

## Rebuilding

```bash
pip install pypdf
python fetch.py
```

PDFs are cached in `pdf/` (gitignored). No CourtListener API key is needed; the text-extraction
endpoint needs one, so the text here is extracted locally from the PDFs instead.
