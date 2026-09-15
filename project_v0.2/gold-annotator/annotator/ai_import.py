"""Reading Copilot's answer and turning it into drafts for the SME to review.

Copilot is asked for JSON Lines: one JSON object per line, starting with a
"meta" line. That format degrades gracefully -- one broken line costs one item,
and an answer cut off mid-way still yields every complete line. The reader also
accepts what models do instead of what they were asked: code fences, chat text
around the answer, a pretty-printed array, a {"items": [...]} wrapper, trailing
commas, curly quotes used as JSON quotes, and Python-style dicts. Every repair
is reported, never silent.

Nothing here decides truth. It only checks structure and finds each quote in
the note. The SME accepts, edits or dismisses every draft.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field

from .spans import _clean_quote, locate

TYPE_ALIASES = {
    "entity": "entity", "person": "entity", "company": "entity", "organization": "entity",
    "organisation": "entity", "party": "entity", "new_entity": "entity",
    "mention": "mention", "reference": "mention", "coreference": "mention", "alias": "mention",
    "detail": "detail", "field": "detail", "attribute": "detail",
    "description": "description", "context": "description", "characterization": "description",
    "role": "description",
    "action": "action", "statement": "action", "relationship": "action", "relation": "action",
    "event": "action",
    "unclear": "unclear", "uncertain": "unclear", "ambiguous": "unclear", "unresolved": "unclear",
    "meta": "meta",
}
ENTITY_KINDS = {
    "person": "person", "people": "person", "individual": "person",
    "organization": "organization", "organisation": "organization", "org": "organization",
    "company": "organization", "business": "organization",
    "location": "location", "place": "location",
    "other": "other", "unknown": "unknown",
}
MENTION_FORMS = {
    "name": "name", "full name": "name", "alias": "alias", "nickname": "alias",
    "short name": "alias", "abbreviation": "alias", "pronoun": "pronoun",
    "description": "description", "descriptive": "description", "title": "description",
}
FIELD_KINDS = {
    "address": "address", "street": "address", "street address": "address",
    "city": "city", "town": "city", "state": "state", "province": "state",
    "zip_code": "zip_code", "zip": "zip_code", "zipcode": "zip_code", "zip code": "zip_code",
    "postal code": "zip_code", "postcode": "zip_code",
    "phone": "phone", "telephone": "phone", "phone number": "phone", "fax": "phone",
    "tin": "TIN", "tax id": "TIN", "tax identification number": "TIN", "ein": "TIN",
    "email": "other", "other": "other",
}
DEPENDENT_TYPES = {"mention", "detail", "description", "action"}
EXISTING_KEY = re.compile(r"^E(\d+)$", re.IGNORECASE)


@dataclass
class Draft:
    seq: int
    line: int
    raw: str
    type: str | None = None
    fields: dict = field(default_factory=dict)       # normalized, SME-editable values
    key: str | None = None
    key2: str | None = None
    quote: str = ""
    start: int | None = None
    end: int | None = None
    match: str = ""                                  # exact | normalized | case | ambiguous | not_found
    candidates: list = field(default_factory=list)
    problems: list = field(default_factory=list)     # must be fixed before accepting
    notes: list = field(default_factory=list)        # informational
    duplicate_of: str | None = None                  # uid of an existing identical record

    def problem(self, code: str, text: str) -> None:
        self.problems.append({"code": code, "text": text})

    @property
    def status(self) -> str:
        if self.duplicate_of:
            return "duplicate"
        return "needs_attention" if self.problems else "ready"

    def to_dict(self) -> dict:
        return {
            "seq": self.seq, "line": self.line, "type": self.type, "fields": self.fields,
            "key": self.key, "key2": self.key2, "quote": self.quote, "start": self.start,
            "end": self.end, "match": self.match, "candidates": self.candidates,
            "problems": self.problems, "notes": self.notes, "status": self.status,
            "duplicate_of": self.duplicate_of, "raw": self.raw,
        }


@dataclass
class Report:
    drafts: list[Draft] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)      # whole-answer problems
    rejected: list[dict] = field(default_factory=list)   # lines that couldn't become drafts
    repairs: list[str] = field(default_factory=list)
    ignored_lines: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict:
        c = {"ready": 0, "needs_attention": 0, "duplicate": 0}
        for d in self.drafts:
            c[d.status] += 1
        c["rejected"] = len(self.rejected)
        c["total"] = len(self.drafts)
        return c

    def to_dict(self) -> dict:
        return {
            "drafts": [d.to_dict() for d in self.drafts], "meta": self.meta, "errors": self.errors,
            "rejected": self.rejected, "repairs": self.repairs, "ignored_lines": self.ignored_lines,
            "truncated": self.truncated, "warnings": self.warnings, "counts": self.counts(),
        }


# ---------------------------------------------------------------------------
# Pulling JSON objects out of whatever Copilot returned
# ---------------------------------------------------------------------------

def extract_objects(text: str) -> tuple[list[tuple[int, str]], bool, list[str]]:
    """Top-level {...} spans (outside strings), whether one was left open, and the leftover lines."""
    objects: list[tuple[int, str]] = []
    depth, start, in_str, esc = 0, -1, False, False
    covered = [False] * len(text)
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"' and depth > 0:
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                objects.append((start, text[start:i + 1]))
                for k in range(start, i + 1):
                    covered[k] = True
    truncated = depth > 0
    if truncated:
        for k in range(start, len(text)):
            covered[k] = True
    leftover_chars = "".join(" " if c else ch for ch, c in zip(text, covered))
    leftover = [ln.strip() for ln in leftover_chars.splitlines() if ln.strip()]
    return objects, truncated, leftover


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def load_object(raw: str) -> tuple[dict | None, str | None]:
    """Parse one object, trying safe repairs in order. Returns (data, repair_used)."""
    attempts = [
        (None, raw),
        ("removed a trailing comma", re.sub(r",\s*([}\]])", r"\1", raw)),
        ("replaced curly quotes used as JSON quotes",
         raw.replace("“", '"').replace("”", '"')),
    ]
    for repair, candidate in attempts:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data, repair
        except (json.JSONDecodeError, ValueError):
            pass
    # A quote copied across a line break often arrives with a raw newline inside the string.
    for repair, candidate in attempts:
        try:
            data = json.loads(candidate, strict=False)
            if isinstance(data, dict):
                return data, "accepted a line break inside a quote"
        except (json.JSONDecodeError, ValueError):
            pass
    # Python-style dict. Only bare JSON literals in value position are translated,
    # so the word "true" inside a quote is never touched.
    pythonic = re.sub(r"(?<=[:\[,])(\s*)(true|false|null)\b",
                      lambda m: m.group(1) + {"true": "True", "false": "False", "null": "None"}[m.group(2)], raw)
    for candidate in (raw, pythonic):
        try:
            data = ast.literal_eval(candidate)
            if isinstance(data, dict):
                return data, "read Python-style quoting"
        except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
            pass
    return None, None


# ---------------------------------------------------------------------------
# Normalizing one item
# ---------------------------------------------------------------------------

def _s(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return str(value).strip() if isinstance(value, str) else ""


def _pick(data: dict, *names: str) -> str:
    lowered = {str(k).strip().lower(): v for k, v in data.items()}
    for n in names:
        if n in lowered:
            return _s(lowered[n])
    return ""


def _occurrence(data: dict) -> int | None:
    raw = _pick(data, "occurrence", "occ", "nth")
    if raw.isdigit() and int(raw) >= 1:
        return int(raw)
    return None


def normalize_item(data: dict, draft: Draft) -> None:
    kind_raw = _pick(data, "type", "kind_of_record", "record", "record_type").lower()
    draft.type = TYPE_ALIASES.get(kind_raw)
    if draft.type is None:
        draft.problem("unknown_type", f"Unknown record type '{kind_raw or '(missing)'}'.")
        return
    if draft.type == "meta":
        return

    draft.quote = _pick(data, "quote", "text", "evidence", "source_text", "span")
    if not draft.quote:
        draft.problem("no_quote", "No words from the note were given. Select them in the note.")
    draft.key = _pick(data, "key", "entity", "entity_key", "ref", "id") or None
    draft.key2 = _pick(data, "key2", "entity2", "second_entity", "second_key", "other_entity") or None
    before = _pick(data, "before", "preceding", "context_before")
    draft.fields["before"] = before
    draft.fields["occurrence"] = _occurrence(data)

    if draft.type == "entity":
        name = _pick(data, "name", "display_name", "label") or draft.quote
        kind = ENTITY_KINDS.get(_pick(data, "kind", "entity_type", "category_type", "class").lower(), "unknown")
        draft.fields.update(name=name, kind=kind)
        if not draft.key:
            draft.problem("no_key", "No key was given, so later items can't refer to this person or company.")
    elif draft.type == "mention":
        form_raw = _pick(data, "form", "mention_form", "reference_form").lower()
        form = MENTION_FORMS.get(form_raw)
        if form is None:
            form = "name"
            draft.notes.append(f"Mention form '{form_raw or 'missing'}' not recognized; defaulted to name.")
        draft.fields["form"] = form
    elif draft.type == "detail":
        field_raw = _pick(data, "field", "field_kind", "detail_kind", "attribute").lower()
        kind = FIELD_KINDS.get(field_raw)
        if kind is None:
            draft.problem("bad_field", f"Detail kind '{field_raw or 'missing'}' isn't one of address, city, "
                                  f"state, zip_code, phone, TIN or other.")
            kind = ""
        draft.fields["field"] = kind
        draft.fields["value"] = _pick(data, "value", "field_value") or draft.quote
    elif draft.type == "description":
        draft.fields["label"] = _pick(data, "label", "open_label")
    elif draft.type == "action":
        draft.fields["label"] = _pick(data, "label", "open_label")
    elif draft.type == "unclear":
        reason = _pick(data, "reason", "why", "explanation")
        draft.fields["reason"] = reason
        if not reason:
            draft.problem("no_reason", "No reason was given for why this is unclear. Add one.")

    if draft.type in DEPENDENT_TYPES and not draft.key:
        draft.problem("no_key", "Doesn't say which person or company this belongs to. Choose one.")
    draft.fields["ai_reason"] = _pick(data, "reason", "why") if draft.type != "unclear" else ""


def _resolve_repeats_by_order(drafts: list[Draft], note_text: str) -> None:
    """Pin down repeated phrases Copilot didn't disambiguate.

    The first time a repeated name appears there are no words before it to
    quote, so Copilot usually can't say which occurrence it means. It is asked
    to list records in reading order, so when it gives exactly as many items
    for a phrase as the note has occurrences, they pair up in order. Otherwise
    an entity takes the earliest occurrence still free, because entities are
    recorded where they are first named. Anything left stays for the SME.
    """
    groups: dict[str, list[Draft]] = {}
    for d in drafts:
        if d.quote:
            groups.setdefault(_clean_quote(d.quote, fold_case=True), []).append(d)
    for group in groups.values():
        pending = [d for d in group if d.match == "ambiguous"]
        if not pending:
            continue
        occurrences = [tuple(c) for c in pending[0].candidates]
        claimed = {(d.start, d.end) for d in group if d.start is not None}
        # "Maria" inside the already-located name "Maria Alvarez" is part of that name,
        # not one of the later mentions Copilot is listing.
        covers = [(d.start, d.end) for d in drafts if d.start is not None and d.type in {"entity", "mention"}
                  and d not in group]
        claimed |= {o for o in occurrences if any(a <= o[0] and o[1] <= b and (a, b) != o for a, b in covers)}
        free = [o for o in occurrences if o not in claimed]
        if len(pending) == len(free):
            pairs = zip(sorted(pending, key=lambda d: d.seq), free)
            how = "the order of Copilot's answer"
        else:
            entities = sorted((d for d in pending if d.type == "entity"), key=lambda d: d.seq)
            pairs = zip(entities, free)
            how = "the first time it's named"
        for d, (s, e) in pairs:
            d.start, d.end, d.quote = s, e, note_text[s:e]
            d.match = "exact"
            d.problems = [p for p in d.problems if p["code"] != "ambiguous"]
            d.notes.append(f"Appears {len(occurrences)} times; picked using {how}. Check it's the right one.")


# ---------------------------------------------------------------------------
# The whole answer
# ---------------------------------------------------------------------------

def split_parts(text: str, size: int) -> list[tuple[int, int]]:
    """Deterministic note parts of roughly `size` characters, cut after a paragraph or sentence."""
    if size <= 0 or len(text) <= size:
        return [(0, len(text))]
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            window = text[start + size // 2:end]
            for sep in ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "):
                cut = window.rfind(sep)
                if cut >= 0:
                    end = start + size // 2 + cut + len(sep)
                    break
        parts.append((start, end))
        start = end
    return parts


def read_answer(answer: str, note_text: str, *, claim: str, note: str,
                existing_entities: dict[int, str], part_size: int = 0,
                already_recorded=None) -> Report:
    """Turn Copilot's answer into drafts located in `note_text`.

    existing_entities maps the claim's entity numbers (E1, E2 ...) to entity ids.
    already_recorded(type, start, end, fields) returns a record uid if identical work exists.
    """
    report = Report()
    text = answer.replace("\r\n", "\n")
    if not text.strip():
        report.errors.append("The answer is empty. Paste Copilot's reply, including its code block.")
        return report

    objects, truncated, leftover = extract_objects(text)
    report.truncated = truncated
    table_lines = [ln for ln in leftover if ln.startswith("|") and ln.count("|") >= 3]
    fence_or_label = re.compile(r"^(```|~~~)")
    report.ignored_lines = sum(1 for ln in leftover if not fence_or_label.match(ln) and ln not in table_lines)
    if not objects:
        if table_lines:
            report.errors.append("Copilot answered with a table instead of the requested format. "
                                 "Ask it: \"Answer again as JSON Lines in one code block.\"")
        elif truncated:
            report.errors.append("The answer was cut off before any complete item. "
                                 "Ask Copilot to answer again for a smaller part of the note.")
        else:
            report.errors.append("No items found. Paste the code block from Copilot's reply.")
        return report
    if truncated:
        report.warnings.append("Copilot's answer was cut off. Every complete item was kept; "
                               "ask Copilot to \"continue from the last item\" and paste the rest into this same note.")

    items: list[tuple[int, str, dict]] = []
    for pos, raw in objects:
        data, repair = load_object(raw)
        line = _line_of(text, pos)
        if data is None:
            if '"' not in raw and "'" not in raw and ":" not in raw:
                report.ignored_lines += 1          # braces in Copilot's chat text, not an item
                continue
            report.rejected.append({"line": line, "raw": raw[:300],
                                    "why": "This line isn't valid JSON and couldn't be repaired."})
            continue
        if repair and repair not in report.repairs:
            report.repairs.append(repair)
        nested = data.get("items") if isinstance(data.get("items"), list) else None
        if nested is not None:
            report.meta.update({k: v for k, v in data.items() if k != "items"})
            for sub in nested:
                if isinstance(sub, dict):
                    items.append((line, json.dumps(sub, ensure_ascii=False), sub))
                else:
                    report.rejected.append({"line": line, "raw": str(sub)[:300], "why": "Not an object."})
            continue
        items.append((line, raw, data))

    parts = split_parts(note_text, part_size) if part_size else [(0, len(note_text))]
    defined: dict[str, int] = {}
    drafts: list[Draft] = []
    for line, raw, data in items:
        draft = Draft(seq=len(drafts) + 1, line=line, raw=raw[:2000])
        normalize_item(data, draft)
        if draft.type == "meta":
            report.meta.update(data)
            continue
        if draft.type is None:
            report.rejected.append({"line": line, "raw": raw[:300], "why": draft.problems[0]["text"]})
            continue
        drafts.append(draft)
        draft.seq = len(drafts)
        if draft.type == "entity" and draft.key:
            k = draft.key.upper()
            if EXISTING_KEY.match(k):
                draft.problem("bad_key", f"Uses {draft.key}, which is reserved for people and companies already "
                                      f"recorded. A new one needs its own key, like P1 or O1.")
            elif k in defined:
                draft.problem("dup_key", f"Key {draft.key} is used for two different people or companies.")
            else:
                defined[k] = draft.seq

    meta_claim, meta_note = _s(report.meta.get("claim")), _s(report.meta.get("note"))
    if (meta_claim and meta_claim != claim) or (meta_note and meta_note != note):
        report.warnings.append(f"This answer says it is for claim {meta_claim or '?'} note {meta_note or '?'}, "
                               f"but you're on claim {claim} note {note}. Check you pasted the right answer.")
    if report.meta.get("read_all") is False:
        report.warnings.append("Copilot says it did not read the whole note. Drafts cover only part of it.")
    part_no = report.meta.get("part")
    prefer = None
    if isinstance(part_no, int) and 1 <= part_no <= len(parts) and len(parts) > 1:
        prefer = parts[part_no - 1]

    for draft in drafts:
        for attr in ("key", "key2"):
            ref = getattr(draft, attr)
            if not ref:
                continue
            m = EXISTING_KEY.match(ref.upper())
            if m:
                if int(m.group(1)) not in existing_entities:
                    draft.problem("unknown_key", f"Refers to {ref}, which isn't one of your recorded people or companies.")
            elif draft.type != "entity" or attr == "key2":
                if ref.upper() not in defined:
                    draft.problem("unknown_key", f"Refers to {ref}, but no person or company with that key was drafted.")
        if draft.quote:
            found = locate(note_text, draft.quote, before=draft.fields.get("before") or None,
                           occurrence=draft.fields.get("occurrence"), prefer=prefer)
            draft.match = found.status
            draft.candidates = [list(c) for c in found.candidates[:50]]
            if found.found:
                draft.start, draft.end = found.start, found.end
                exact = note_text[found.start:found.end]
                if found.status == "normalized":
                    draft.notes.append("Adjusted to the note's exact characters (spacing or quote marks differed).")
                elif found.status == "case":
                    draft.notes.append("Matched ignoring capital letters. Check these are the right words.")
                if found.how:
                    draft.notes.append(f"Appears {len(found.candidates)} times; picked using {found.how}.")
                draft.quote = exact
            elif found.status == "ambiguous":
                draft.problem("ambiguous", f"These words appear {len(found.candidates)} times. Pick the right one in the note.")
            else:
                draft.problem("not_found", "Couldn't find these words in the note. Select the right words, or dismiss this draft.")

    _resolve_repeats_by_order(drafts, note_text)

    # Only once every position is final: a repeated name has none until the step above.
    if already_recorded:
        for draft in drafts:
            if draft.start is not None and not draft.problems:
                uid = already_recorded(draft.type, draft.start, draft.end, draft.fields)
                if uid:
                    draft.duplicate_of = uid

    seen: dict[tuple, int] = {}
    for draft in drafts:
        if draft.start is None or draft.duplicate_of:
            continue
        sig = (draft.type, draft.start, draft.end, draft.fields.get("field", ""), (draft.key or "").upper())
        if sig in seen:
            draft.duplicate_of = f"draft #{seen[sig]}"
        else:
            seen[sig] = draft.seq

    report.drafts = drafts
    if not drafts and not report.rejected:
        summary = _s(report.meta.get("summary"))
        report.errors.append("Copilot found nothing to record in this note" + (f" (“{summary}”)" if summary else "") +
                             ". That can be right, for an administrative note. Read it yourself to confirm, "
                             "then record anything it missed.")
    return report
