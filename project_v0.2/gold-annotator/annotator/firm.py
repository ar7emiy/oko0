"""Reading the firm's export (one row per entity the firm's tool reported)."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from xml.etree.ElementTree import ParseError
from pathlib import Path

from . import workbook

COLUMNS = [
    "claim_number", "recordType", "entity_category_name", "entity_subcategory_name", "entity_name",
    "entity_address", "entity_city", "entity_state", "entity_zip_code", "entity_phone", "entity_TIN",
    "entity_NER_tag", "Entity_Watchlist_flag", "Exact_search_Note_ID",
    "Exact_search_matched_watchlist_entity_name", "GenAI_search_Note_ID", "GenAI_entityNameClearned",
    "GenAI_tok_sort_similarity", "Watchlist_entity_id", "Watchlist_entity_name", "watchlist_address",
    "watchlist_city", "watchlist_state", "watchlist_zip_code", "watchlist_phone", "watchlist_TIN",
]
# Firm column -> the detail kind SMEs record for it.
DETAIL_COLUMNS = {
    "entity_address": "address", "entity_city": "city", "entity_state": "state",
    "entity_zip_code": "zip_code", "entity_phone": "phone", "entity_TIN": "TIN",
}
NER_TO_TYPE = {"PERSON": "person", "PER": "person", "ORG": "organization", "ORGANIZATION": "organization",
               "LOC": "location", "GPE": "location", "LOCATION": "location"}

ALIASES = {c.casefold(): c for c in COLUMNS}
ALIASES.update({
    "recordtype (entity/ genai_only/ exact_search)": "recordType",
    "entity_category": "entity_category_name", "entity_subcategory": "entity_subcategory_name",
    "entity_zip": "entity_zip_code", "entity_ner": "entity_NER_tag",
    "genai_note_id": "GenAI_search_Note_ID", "genai_entitynamecleaned": "GenAI_entityNameClearned",
})


def note_ids(value: str) -> list[str]:
    """Normalize citation tokens only; keep source cells and leading zeros intact."""
    result = []
    for token in (value or "").split(","):
        token = token.strip()
        if re.fullmatch(r"[0-9]+\.0+", token):
            token = token.split(".")[0]
        if token and token not in result:
            result.append(token)
    return result


def cited_notes(data: dict) -> list[str]:
    return list(dict.fromkeys(note_ids(data.get("Exact_search_Note_ID", "")) +
                              note_ids(data.get("GenAI_search_Note_ID", ""))))


def is_flagged(data: dict) -> bool:
    return str(data.get("Entity_Watchlist_flag", "")).strip().lower() in {"1", "true", "yes", "y"}


def load(paths: list[Path]) -> tuple[list[dict], list[str], str]:
    """Rows from CSV/XLSX tables, warnings, and a fingerprint of source bytes."""
    rows: list[dict] = []
    warnings: list[str] = []
    digest = hashlib.sha256()
    counters: dict[str, int] = {}
    for path in paths:
        if not path.exists():
            warnings.append(f"Firm export not found: {path}")
            continue
        raw = path.read_bytes()
        digest.update(raw)
        try:
            sheets = list(workbook.tables(raw)) if zipfile.is_zipfile(io.BytesIO(raw)) else [
                (path.name, list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""))))]
        except (ValueError, KeyError, IndexError, ParseError, zipfile.BadZipFile) as exc:
            warnings.append(f"{path.name}: could not read export ({exc}); skipped.")
            continue
        for sheet, records in sheets:
            records = [r for r in records if any(v.strip() for v in r)]
            if not records:
                continue
            header = [h.strip() for h in records[0]]
            mapped = [ALIASES.get(h.casefold(), h) for h in header]
            label = f"{path.name} [{sheet}]"
            if len(set(h for h in mapped if h)) != len([h for h in mapped if h]):
                warnings.append(f"{label}: ambiguous duplicate columns; skipped.")
                continue
            if "claim_number" not in mapped or "entity_name" not in mapped:
                warnings.append(f"{label}: needs at least claim_number and entity_name columns; skipped.")
                continue
            missing = [c for c in COLUMNS if c not in mapped]
            if missing:
                warnings.append(f"{label}: missing columns {', '.join(missing)} (treated as empty).")
            for record in records[1:]:
                data = {c: "" for c in COLUMNS}
                for i, canonical in enumerate(mapped):
                    if canonical:
                        value = record[i] if i < len(record) else ""
                        data[canonical] = value.strip()
                        if header[i] != canonical:
                            data[header[i]] = value
                claim = data["claim_number"]
                if not claim:
                    continue
                counters[claim] = counters.get(claim, 0) + 1
                rows.append({"id": f"{claim}#{counters[claim]}", "claim": claim, "seq": counters[claim], "data": data})
    return rows, warnings, digest.hexdigest()[:16]


def categories(rows: list[dict]) -> list[str]:
    return sorted({r["data"]["entity_category_name"] for r in rows if r["data"].get("entity_category_name")})
