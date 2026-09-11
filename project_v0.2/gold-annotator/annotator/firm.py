"""Reading the firm's export (one row per entity the firm's tool reported)."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

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


def is_flagged(data: dict) -> bool:
    return str(data.get("Entity_Watchlist_flag", "")).strip().lower() in {"1", "true", "yes", "y"}


def load(paths: list[Path]) -> tuple[list[dict], list[str], str]:
    """Rows from each CSV, warnings, and a combined fingerprint of the sources."""
    rows: list[dict] = []
    warnings: list[str] = []
    digest = hashlib.sha256()
    for path in paths:
        if not path.exists():
            warnings.append(f"Firm export not found: {path}")
            continue
        raw = path.read_bytes()
        digest.update(raw)
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(text.splitlines())
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in COLUMNS if c not in header]
        if "claim_number" not in header or "entity_name" not in header:
            warnings.append(f"{path.name}: needs at least claim_number and entity_name columns; skipped.")
            continue
        if missing:
            warnings.append(f"{path.name}: missing columns {', '.join(missing)} (treated as empty).")
        counters: dict[str, int] = {}
        for record in reader:
            data = {c: (record.get(c) or "").strip() for c in COLUMNS}
            for extra in header:
                if extra not in data:
                    data[extra] = (record.get(extra) or "").strip()
            claim = data["claim_number"]
            if not claim:
                continue
            counters[claim] = counters.get(claim, 0) + 1
            rows.append({"id": f"{claim}#{counters[claim]}", "claim": claim, "seq": counters[claim], "data": data})
    return rows, warnings, digest.hexdigest()[:16]


def categories(rows: list[dict]) -> list[str]:
    return sorted({r["data"]["entity_category_name"] for r in rows if r["data"].get("entity_category_name")})
