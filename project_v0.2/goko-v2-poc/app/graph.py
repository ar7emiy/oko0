"""An in-memory, read-only view of one pipeline run.

Loads what the notebook wrote (mentions.json, links.json, envelope_*.json,
dossier_*.json, run_info.json) plus the note texts, and answers the questions
the interface asks: what matches this text, what is this entity at this lens,
where is this identifier, what does this note say, what is relevant to this
question. Merged entities come from goko.projection, the same code the
notebook's dossiers use, so the app can never show a merge the notebook would
not make.
"""
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from goko.projection import LENSES, admits, project, subtree_weakest
from goko.watchlist import flags_for, near_flags

EXCERPT = 180          # characters of context either side of a span
# source passages for the librarian: characters either side of a hit, the longest a merged
# window may grow, how many passages a question gets, and phrase hits per note
PASSAGE_WIDTH, PASSAGE_MAX, PASSAGE_CAP, PASSAGES_PER_NOTE = 300, 1200, 10, 3
QUESTION_STOP = {"the", "a", "an", "of", "and", "or", "is", "are", "was", "who", "what", "which",
                 "how", "did", "does", "do", "in", "on", "to", "for", "with", "by", "at", "any",
                 "all", "there", "were", "be", "been", "it", "its", "their", "his", "her", "about",
                 "tell", "me", "show", "list", "find", "why", "when", "where"}

# Identifiers the page never needs in full: shown as their last four digits, addressed by
# an opaque token, and blanked in note text. The server keeps the value to match searches.
MASKED_TYPES = {"ssn", "bank_account"}
MASK = "\u2022"
_SSN_SHAPE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _stem(w):
    """Crude suffix strip so 'referred', 'referral' and 'refer' meet; 'billed' and 'billing'."""
    for suf in ("ations", "ation", "ings", "ing", "als", "al", "ers", "er", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    return w[:-1] if len(w) > 4 and w[-1] == w[-2] else w       # 'referr' -> 'refer'


def mask_digits(s, keep=4):
    """Every digit but the last `keep` becomes a dot; length and punctuation survive, so
    spans computed on the original text still point at the same characters."""
    total = sum(c.isdigit() for c in s)
    out, seen = [], 0
    for c in s:
        if c.isdigit():
            seen += 1
            out.append(c if seen > total - keep else MASK)
        else:
            out.append(c)
    return "".join(out)


def masked_value(t, v):
    """How a masked identifier is shown: SSN as its last four, an account as its last four
    with the (public) routing number of its bank."""
    if t == "ssn":
        return f"{MASK * 3}-{MASK * 2}-{v[-4:]}"
    if t == "bank_account":
        routing, _, acct = v.rpartition(":")
        return f"acct {MASK * 4}{acct[-4:]}" + (f", routing {routing}" if routing else "")
    return v


def public_ident(t, v):
    """The id the page uses for an identifier. Masked types get an opaque token."""
    if t in MASKED_TYPES:
        return f"{t}:#{hashlib.sha1(f'{t}:{v}'.encode()).hexdigest()[:12]}"
    return f"{t}:{v}"


class Run:
    def __init__(self, run_dir, notes_dir=None):
        self.dir = Path(run_dir)
        rd = self.dir
        self.info = json.loads((rd / "run_info.json").read_text(encoding="utf-8")) \
            if (rd / "run_info.json").exists() else {}
        self.mentions = {m["key"]: m for m in json.loads((rd / "mentions.json").read_text(encoding="utf-8"))}
        self.links = json.loads((rd / "links.json").read_text(encoding="utf-8"))
        self.envelopes = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(rd.glob("envelope_*.json"))]
        self.dossiers = {}
        for p in sorted(rd.glob("dossier_*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            self.dossiers[d["claim_id"]] = d
        cc = rd / "cross_claim.json"
        self.cross = json.loads(cc.read_text(encoding="utf-8")) if cc.exists() else {}
        # watchlist links (cell 18c): corpus mention -> OIG LEIE record, scored like any link
        wl = rd / "watchlist_links.json"
        self.watchlist = json.loads(wl.read_text(encoding="utf-8")) if wl.exists() else {
            "links": [], "records": {}, "records_on_list": 0}
        self.wl_by_mention = defaultdict(list)
        for l in self.watchlist["links"]:
            self.wl_by_mention[l["a"]].append(l)

        # note texts: run_info names each file; otherwise look in notes_dir
        self.notes = {}
        files = {k: v["file"] for k, v in self.info.get("notes", {}).items()}
        if not files and notes_dir:
            for f in Path(notes_dir).glob("*.txt"):
                m = re.match(r".*_(\d+)\.txt$", f.name)
                if m:
                    files[f"note:{m.group(1)}"] = str(f)
        for env in self.envelopes:
            f = files.get(env["note_key"])
            text = open(f, encoding="utf-8", errors="replace", newline="").read() if f and Path(f).exists() else ""
            self.notes[env["note_key"]] = {"text": text, "claim_id": env["claim_id"],
                                           "note_id": env["note_id"], "file": f}

        # masked identifiers: blank them in the note text (length-preserving, so every span
        # stays valid) and remember the raw strings, so quotes and labels are masked too
        self.ident_of_public = {}
        self._masked_raw = set()
        for env in self.envelopes:
            n = self.notes[env["note_key"]]
            text = n["text"]
            for d in env["detail_mentions"]:
                if d["detail_type"] not in MASKED_TYPES:
                    continue
                self._masked_raw.add(d["raw_value"])
                span = d.get("raw_span") or d.get("clean_span")
                if span and text:
                    s, e = span
                    text = text[:s] + mask_digits(text[s:e]) + text[e:]
            n["text"] = _SSN_SHAPE.sub(lambda m: mask_digits(m.group(0)), text)

        # details and actions indexed by owning mention
        self.details_of = defaultdict(list)
        self.detail_owners = defaultdict(set)
        self.actions = []
        for env in self.envelopes:
            nk = env["note_key"]
            for d in env["detail_mentions"]:
                span = d.get("raw_span") or d.get("clean_span")
                t, v = d["detail_type"], d["normalized"]
                rec = {"type": t, "value": v,
                       "raw": masked_value(t, v) if t in MASKED_TYPES and v else self.redact(d["raw_value"]),
                       "ident": public_ident(t, v) if v else None,
                       "basis": d.get("basis"), "note": nk, "span": span,
                       "checksum": d.get("checksum"), "detected_by": d.get("detected_by"),
                       "subtype": d.get("subtype"), "parts": d.get("parts")}
                if v:
                    self.ident_of_public[rec["ident"]] = f"{t}:{v}"
                owner = f"{nk}:{d['owner_ref']}" if d.get("owner_ref") not in (None, "UNASSIGNED") else None
                rec["owner"] = owner
                if owner:
                    self.details_of[owner].append(rec)
                if d["normalized"]:
                    self.detail_owners[f"{d['detail_type']}:{d['normalized']}"].add(owner)
                    self.details_of[f"id:{d['detail_type']}:{d['normalized']}"].append(rec)
            for a in env["action_mentions"]:
                self.actions.append({
                    "id": f"{nk}:{a['action_id']}", "note": nk, "claim_id": env["claim_id"],
                    "type": a["action_type"], "quote": self.redact(a["quote"]), "stance": a.get("stance"),
                    "time": a.get("time_qualifier"), "span": a.get("raw_span") or a.get("clean_span"),
                    "participants": [{"mention": f"{nk}:{p['mention_id']}", "role": p["role"]}
                                     for p in a["participants"]]})
        self.actions_of = defaultdict(list)
        for a in self.actions:
            for p in a["participants"]:
                self.actions_of[p["mention"]].append(a)
        self.links_of = defaultdict(list)
        self.link_index = {}
        for l in self.links:
            self.links_of[l["a"]].append(l); self.links_of[l["b"]].append(l)
            self.link_index[(l["a"], l["b"])] = self.link_index[(l["b"], l["a"])] = l
        for l in self.watchlist["links"]:
            self.link_index[(l["a"], l["b"])] = self.link_index[(l["b"], l["a"])] = l
        # categories from the frozen claim dossiers, per mention
        self.category_of = {}
        for d in self.dossiers.values():
            for e in d["entities"]:
                for k in e["merge_provenance"]["members"]:
                    self.category_of[k] = {"value": e["category"]["value"],
                                           "subcategory": e.get("subcategory"),
                                           "claim_entity": e["entity_id"]}
        self._proj = {}

    def redact(self, s):
        """A string with every masked identifier in it blanked to its last four digits."""
        if not s:
            return s
        for raw in self._masked_raw:
            if raw and raw in s:
                s = s.replace(raw, mask_digits(raw))
        return _SSN_SHAPE.sub(lambda m: mask_digits(m.group(0)), s)

    # ---- projection ----------------------------------------------------------------
    def projection(self, lens):
        if lens not in LENSES:
            lens = "default"
        if lens not in self._proj:
            pr = project(list(self.mentions), self.links, lens)
            pr["cluster_of"] = {k: c for c in pr["clusters"] for k in c["members"]}
            self._proj[lens] = pr
        return self._proj[lens]

    def cluster(self, key, lens):
        return self.projection(lens)["cluster_of"].get(key)

    def title_of(self, members):
        """The fullest name made only of words at least two members use.

        One member's odd form ("Dr. Monroe office", a model mislabel) never becomes the
        title of a cluster that otherwise agrees on "Dr. Monroe"."""
        names = [self.mentions[k]["name"] for k in members]
        if len(set(names)) == 1:
            return names[0]
        count = defaultdict(int)
        for n in set(names):
            for w in set(_norm(n).split()):
                count[w] += names.count(n)
        agreed = {w for w, c in count.items() if c >= 2}
        ok = [n for n in names if set(_norm(n).split()) <= agreed] or names
        return max(ok, key=lambda n: (len(_norm(n).split()), ok.count(n), len(n)))

    # ---- evidence ------------------------------------------------------------------
    def excerpt(self, note_key, span):
        text = self.notes.get(note_key, {}).get("text", "")
        if not text or not span:
            return None
        s, e = span
        a, b = max(0, s - EXCERPT), min(len(text), e + EXCERPT)
        # widen to whitespace so the excerpt does not start or end mid-word
        while a > 0 and not text[a - 1].isspace() and s - a < EXCERPT + 30: a -= 1
        while b < len(text) and not text[b].isspace() and b - e < EXCERPT + 30: b += 1
        return {"note": note_key, "claim_id": self.notes[note_key]["claim_id"],
                "before": text[a:s], "match": text[s:e], "after": text[e:b],
                "span": [s, e], "window": [a, b],
                "clipped_left": a > 0, "clipped_right": b < len(text)}

    def note_text(self, note_key):
        n = self.notes.get(note_key)
        return {"note": note_key, "claim_id": n["claim_id"], "text": n["text"]} if n else None

    def _wl_ref(self, l):
        rec = self.watchlist["records"].get(l["b"], {})
        return {"record_id": l["b"], "record": rec, "mention": l["a"],
                "mention_name": self.mentions[l["a"]]["name"] if l["a"] in self.mentions else l["a"],
                "p": l["p"], "basis_class": l["basis_class"], "veto": l.get("veto"),
                "admitted": [x for x in LENSES if self._admits(l, x)]}

    @staticmethod
    def _admits(l, lens):
        return admits(l, lens)

    def _by_record(self, links):
        """One row per watchlist record: its strongest link, and every member that links."""
        out = {}
        for l in links:                               # strongest first
            row = out.get(l["b"])
            if row is None:
                out[l["b"]] = {**self._wl_ref(l), "links": 1, "mentions": [l["a"]]}
            else:
                row["links"] += 1
                row["mentions"].append(l["a"])
        return list(out.values())

    def flag_of(self, members, lens):
        """Flagged for review at this lens: the admitted watchlist links of any member,
        one row per listed record."""
        return self._by_record(flags_for(members, self.wl_by_mention, lens))

    def _entity_ref(self, key, lens):
        c = self.cluster(key, lens)
        members = c["members"] if c else [key]
        return {"kind": "entity", "id": c["id"] if c else key, "name": self.title_of(members),
                "type": self.mentions[key]["type"]}

    # ---- the decision card ---------------------------------------------------------
    def _mask_link(self, l):
        """A copy of a link safe for the page: masked identifiers shown as their last four."""
        l = json.loads(json.dumps(l))
        def mv(t, v):
            return masked_value(t, v) if t in MASKED_TYPES and v else v
        l["weights"] = {(f"{k.split(':', 1)[0]}:{mv(*k.split(':', 1))}" if ":" in k else k): v
                        for k, v in l["weights"].items()}
        for r in l.get("fields", []):
            t = r.get("type")
            if t in MASKED_TYPES:
                r["value"] = mv(t, r.get("value"))
                r["a"] = [mv(t, x) for x in r.get("a") or []]
                r["b"] = [mv(t, x) for x in r.get("b") or []]
        if l.get("veto") and l["veto"].split(":", 1)[0] in {f"conflicting_{t}" for t in MASKED_TYPES}:
            l["veto"] = self.redact(re.sub(r"\d{5,}", lambda m: mask_digits(m.group(0)), l["veto"]))
        return l

    def _mention_side(self, key, lens):
        m = self.mentions[key]
        return {"kind": "mention", "key": key, "name": m["name"],
                "name_as_extracted": m.get("name_as_extracted"), "type": m["type"],
                "role_class": m["role_class"], "claim_id": m["claim_id"], "note": m["note_key"],
                "entity": self._entity_ref(key, lens), "roles": m.get("roles", [])[:6],
                "locations": m.get("locations", []),
                "evidence": self.excerpt(m["note_key"], m.get("raw_span") or m.get("clean_span"))}

    def lens_outcomes(self, l):
        """For each lens: is the link admitted, and if not, why; and what the projection did
        with it (merged by it, merged through other links, or the union refused)."""
        out = []
        for lens, spec in LENSES.items():
            adm = admits(l, lens)
            why = None
            if not adm:
                why = ("veto" if l.get("veto") else "no_agreement" if l["basis_class"] == "none"
                       else "below_min" if l["p"] < spec["min_p"] else "basis")
            row = {"lens": lens, "min_p": spec["min_p"], "identifier_only": spec["basis"] is not None,
                   "admitted": adm, "why_not": why}
            if l.get("source") == "oig_leie":
                row["flags"] = adm
            else:
                pr = self.projection(lens)
                ca, cb = pr["cluster_of"].get(l["a"]), pr["cluster_of"].get(l["b"])
                row["merged"] = ca is not None and ca is cb
                row["by_this_link"] = row["merged"] and any(
                    (e["a"], e["b"]) == (l["a"], l["b"]) for e in ca["edges"])
                ref = next((r for r in pr["refused"]
                            if (r["link"]["a"], r["link"]["b"]) == (l["a"], l["b"])), None)
                if ref:
                    row["refused"] = {"reason": ref["reason"],
                                      "would_merge": [self.mentions[k]["name"] for k in ref.get("would_merge", [])
                                                      if k in self.mentions],
                                      "would_reach": ref.get("would_reach")}
            out.append(row)
        return out

    def link_card(self, a, b, lens="default"):
        l = self.link_index.get((a, b))
        if l is None:
            return None
        watch = l.get("source") == "oig_leie"
        rec = self.watchlist["records"].get(l["b"]) if watch else None
        return {"kind": "link", "link": self._mask_link(l), "watchlist": watch,
                "a": self._mention_side(l["a"], lens),
                "b": ({"kind": "record", "record_id": l["b"], "record": rec,
                       "source": self.watchlist.get("source")} if watch
                      else self._mention_side(l["b"], lens)),
                "lens": lens, "lenses": self.lens_outcomes(l),
                "lens_specs": {k: {"min_p": v["min_p"], "identifier_only": v["basis"] is not None,
                                   "label": v["label"]} for k, v in LENSES.items()}}

    def _cand_row(self, l, members, lens, merged):
        inside = l["a"] if l["a"] in members else l["b"]
        other = l["b"] if inside == l["a"] else l["a"]
        return {"a": l["a"], "b": l["b"], "via": self.mentions[inside]["name"],
                "other": {**self._entity_ref(other, lens), "mention_name": self.mentions[other]["name"],
                          "claim_id": self.mentions[other]["claim_id"]},
                "p": l["p"], "basis_class": l["basis_class"], "veto": l.get("veto"),
                "similarity": l.get("name_similarity_pct", round(100 * (l.get("name_similarity") or 0))),
                "distance": l["distance"], "merged": merged}

    def candidates(self, members, cluster, lens, n=12):
        """The closest mentions around an entity: the links that merged its members, and the
        strongest link to each entity this lens kept apart (vetoed ones included)."""
        ms = set(members)
        merged = [self._cand_row(cluster["joined_by"][k], ms, lens, True)
                  for k in members if cluster and cluster["joined_by"].get(k)]
        best = {}
        for k in members:
            for l in self.links_of[k]:
                other = l["b"] if l["a"] == k else l["a"]
                if other in ms:
                    continue
                oc = self.cluster(other, lens)
                oid = oc["id"] if oc else other
                if oid not in best or l["p"] > best[oid]["p"]:
                    best[oid] = l
        apart = sorted(best.values(), key=lambda l: -l["p"])[:n]
        return {"merged": sorted(merged, key=lambda r: -r["p"])[:n],
                "not_merged": [self._cand_row(l, ms, lens, False) for l in apart],
                "not_merged_total": len(best)}

    # ---- views ---------------------------------------------------------------------
    def entity_view(self, key, lens="default"):
        if key not in self.mentions:
            return None
        c = self.cluster(key, lens)
        members = c["members"] if c else [key]
        head = self.mentions[members[0]]
        claims = sorted({self.mentions[k]["claim_id"] for k in members})

        mem = []
        for k in members:
            m = self.mentions[k]
            j = c["joined_by"].get(k) if c else None
            mem.append({"key": k, "name": m["name"], "claim_id": m["claim_id"], "note": m["note_key"],
                        "role_class": m["role_class"], "category": self.category_of.get(k),
                        "joined_by": ({"with": j["b"] if j["a"] == k else j["a"],
                                       "with_name": self.mentions[j["b"] if j["a"] == k else j["a"]]["name"],
                                       "p": j["p"], "basis_class": j["basis_class"],
                                       "distance": j["distance"]} if j else None),
                        "evidence": self.excerpt(m["note_key"], m.get("raw_span") or m.get("clean_span"))})

        folded, specialties = {}, []
        for k in members:
            for d in self.details_of[k]:
                if d["type"] == "provider_specialty":
                    if d["raw"] not in specialties:
                        specialties.append(d["raw"])
                    continue
                f = folded.setdefault((d["type"], d["value"]), {
                    "type": d["type"], "value": d["value"], "ident": d["ident"], "raw": d["raw"],
                    "basis": d["basis"], "checksum": d["checksum"], "subtype": d.get("subtype"),
                    "parts": d.get("parts"),
                    "masked": d["type"] in MASKED_TYPES, "evidence": [], "shared_with": []})
                f["subtype"] = f["subtype"] or d.get("subtype")
                f["evidence"].append(self.excerpt(d["note"], d["span"]))
        for f in folded.values():
            others = {o for o in self.detail_owners[f"{f['type']}:{f['value']}"] if o and o not in members}
            f["shared_with"] = sorted({json.dumps(self._entity_ref(o, lens)) for o in others})
            f["shared_with"] = [json.loads(x) for x in f["shared_with"]]
            f.pop("value")                     # the page gets `ident` and the display form

        acts, related, group_members, member_of = [], {}, {}, {}
        for k in members:
            for a in self.actions_of[k]:
                if a["type"] == "member_of":
                    me = next(p["role"] for p in a["participants"] if p["mention"] == k)
                    for p in a["participants"]:
                        if p["mention"] in members or p["mention"] not in self.mentions:
                            continue
                        ref = self._entity_ref(p["mention"], lens)
                        if me == "group" and p["role"] != "group":
                            group_members.setdefault(ref["id"], {**ref, "evidence": self.excerpt(a["note"], a["span"])})
                        elif me != "group" and p["role"] == "group":
                            member_of.setdefault(ref["id"], ref)
                role = next(p["role"] for p in a["participants"] if p["mention"] == k)
                others = []
                for p in a["participants"]:
                    if p["mention"] in members or p["mention"] not in self.mentions:
                        continue
                    ref = {**self._entity_ref(p["mention"], lens), "role": p["role"]}
                    others.append(ref)
                    related.setdefault(ref["id"], {**ref, "count": 0})["count"] += 1
                acts.append({"id": a["id"], "type": a["type"], "role": role, "stance": a["stance"],
                             "time": a["time"], "others": others,
                             "evidence": self.excerpt(a["note"], a["span"])})

        # links this lens left out: the merges a reader may want to consider
        outside = []
        for k in members:
            for l in self.links_of[k]:
                other = l["b"] if l["a"] == k else l["a"]
                if other in members or l["p"] < LENSES["broad"]["min_p"]:
                    continue
                outside.append({**self._entity_ref(other, lens), "p": l["p"],
                                "basis_class": l["basis_class"], "veto": l["veto"],
                                "distance": l["distance"], "via": k,
                                "name_agreement": l["name_agreement"],
                                "co_party": l["co_party"]})
        best = {}
        for o in sorted(outside, key=lambda o: -o["p"]):
            best.setdefault(o["id"], o)

        weakest = c["weakest"] if c else None
        cands = self.candidates(members, c, lens)
        refused = [r for r in self.projection(lens)["refused"]
                   if r["link"]["a"] in members or r["link"]["b"] in members]
        flags = self.flag_of(members, lens)
        near = self._by_record(near_flags(members, self.wl_by_mention, lens))[:8]
        return {
            "kind": "entity", "id": members[0], "lens": lens, "lenses": list(LENSES),
            "title": self.title_of(members), "type": head["type"],
            "role_class": sorted({self.mentions[k]["role_class"] for k in members}),
            "claims": claims, "mention_count": len(members),
            "confidence": weakest["p"] if weakest else None,
            "weakest_link": ({"a": weakest["a"], "b": weakest["b"], "p": weakest["p"],
                              "basis_class": weakest["basis_class"],
                              "a_name": self.mentions[weakest["a"]]["name"],
                              "b_name": self.mentions[weakest["b"]]["name"]} if weakest else None),
            "basis_classes": sorted({e["basis_class"] for e in (c["edges"] if c else [])}),
            "categories": sorted({json.dumps({"value": self.category_of[k]["value"],
                                              "subcategory": self.category_of[k]["subcategory"]})
                                  for k in members if k in self.category_of}),
            "members": mem, "details": list(folded.values()), "actions": acts,
            "kind_of_party": self.kind_of(members), "specialties": specialties,
            "group_members": list(group_members.values()), "member_of": list(member_of.values()),
            "related": sorted(related.values(), key=lambda r: -r["count"]),
            "not_merged": list(best.values())[:12],
            "candidates": cands,
            "category_line": self._category_line(members),
            "flagged": flags, "watchlist_near": near,
            "watchlist_source": {"name": self.watchlist.get("source"),
                                 "records_on_list": self.watchlist.get("records_on_list")},
            "refused": [{"reason": r["reason"], "a": r["link"]["a"], "b": r["link"]["b"]} for r in refused],
        }

    def kind_of(self, members):
        """party, group (a collective the note defines) or construct (an enterprise, a
        scheme): the kind most of the entity's mentions carry."""
        kinds = [self.mentions[k].get("kind", "party") for k in members]
        return max(set(kinds), key=kinds.count) if kinds else "party"

    def _category_line(self, members):
        """The model's reading of the party's role, per claim; not part of identity."""
        seen = []
        for k in members:
            c = self.category_of.get(k)
            if not c:
                continue
            v = "undetermined" if c["value"] == "insufficient_evidence" else c["value"].replace("_", " ")
            s = (c.get("subcategory") or "").replace("_", " ")
            txt = f"{v} · {s}" if s else v
            if txt not in seen:
                seen.append(txt)
        return seen

    def entity_list(self, lens="default"):
        """Every entity at a lens, for the left-hand list: Flagged for review first,
        strongest flag first, then alphabetical. Forms are included for the filter box."""
        pr = self.projection(lens)
        if "list" in pr:
            return pr["list"]
        out = []
        for c in pr["clusters"]:
            ms = c["members"]
            flags = flags_for(ms, self.wl_by_mention, lens)
            near = near_flags(ms, self.wl_by_mention, lens, floor=0.1) if not flags else []
            near = [l for l in near if not l.get("veto")]
            out.append({
                "id": c["id"], "name": self.title_of(ms), "type": self.mentions[c["id"]]["type"],
                "kind": self.kind_of(ms),
                "mentions": len(ms), "claims": len({self.mentions[k]["claim_id"] for k in ms}),
                "flag": ({"p": flags[0]["p"], "basis_class": flags[0]["basis_class"],
                          "record": self.watchlist["records"].get(flags[0]["b"], {}).get("name")}
                         if flags else None),
                "near": {"p": near[0]["p"], "admitted": [x for x in LENSES if admits(near[0], x)]} if near else None,
                "forms": sorted({f for k in ms for f in self.mentions[k]["forms"]})[:12]})
        out.sort(key=lambda e: (0 if e["flag"] else 1, -(e["flag"]["p"] if e["flag"] else 0),
                                _norm(e["name"]), e["id"]))
        pr["list"] = out
        return out

    def identifier_view(self, ident, lens="default"):
        ident = self.ident_of_public.get(ident, ident)
        recs = self.details_of.get(f"id:{ident}")
        if not recs:
            return None
        t, v = ident.split(":", 1)
        holders = {}
        for r in recs:
            if r["owner"] and r["owner"] in self.mentions:
                ref = self._entity_ref(r["owner"], lens)
                holders.setdefault(ref["id"], {**ref, "claims": set()})["claims"].add(
                    self.mentions[r["owner"]]["claim_id"])
        for h in holders.values():
            h["claims"] = sorted(h["claims"])
        claims = sorted({self.notes[r["note"]]["claim_id"] for r in recs})
        shared = next((s for s in self.cross.get("shared_details", [])
                       if s["detail_type"] == t and s["value"] == v), None)
        return {"kind": "identifier", "id": public_ident(t, v), "title": recs[0]["raw"], "detail_type": t,
                "masked": t in MASKED_TYPES, "lens": lens, "claims": claims,
                "holders": list(holders.values()),
                "unassigned": sum(1 for r in recs if not r["owner"]),
                "suspicion": shared["suspicion"] if shared else None,
                "distance": shared["distance"] if shared else None,
                "evidence": [self.excerpt(r["note"], r["span"]) for r in recs]}

    def _occurrences(self, env, text):
        """Every other place a note names each of its mentions: the mention's own name forms
        (name-like, same family: the notebook's `forms`) found again inside the chunk the
        mention came from. A place two mentions both claim goes to the one whose own span is
        nearer; a place inside another mention's own span is left to that mention."""
        chunk_of = {m["mention_id"]: (m.get("_chunk") or [0, len(text)]) for m in env["entity_mentions"]}
        own = []
        for m in env["entity_mentions"]:
            s = m.get("raw_span") or m.get("clean_span")
            if s:
                own.append(tuple(s))
        claims = {}
        for m in env["entity_mentions"]:
            key = f"{env['note_key']}:{m['mention_id']}"
            rec = self.mentions.get(key)
            if not rec:
                continue
            w0, w1 = chunk_of[m["mention_id"]]
            anchor = (m.get("raw_span") or m.get("clean_span") or [w0])[0]
            forms = sorted({f for f in rec.get("forms", []) if len(f.strip()) >= 3}, key=len, reverse=True)
            for f in forms:
                rx = re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(map(re.escape, f.split())) + r"(?![A-Za-z0-9])", re.I)
                for hit in rx.finditer(text, w0, w1):
                    s, e = hit.span()
                    if any(s < b and a < e for a, b in own):
                        continue
                    prev = claims.get((s, e))
                    if prev is None or abs(anchor - s) < prev[1]:
                        claims[(s, e)] = (key, abs(anchor - s))
        out = defaultdict(list)
        taken = []
        for (s, e), (key, _) in sorted(claims.items(), key=lambda x: (x[0][0], -(x[0][1] - x[0][0]))):
            if any(s < b and a < e for a, b in taken):
                continue                      # a longer form already covers these characters
            taken.append((s, e))
            out[key].append([s, e])
        return out

    def note_view(self, note_key, lens="default", span=None):
        """A note with everything extracted from it placed: each entity mention (and the other
        places the note names it), each detail with its owner, each action with who takes
        part. The page layers them; nothing here is inferred beyond the notebook's spans."""
        n = self.notes.get(note_key)
        if not n:
            return None
        env = next(e for e in self.envelopes if e["note_key"] == note_key)
        text = n["text"]
        ms = sorted((m for m in self.mentions.values() if m["note_key"] == note_key),
                    key=lambda m: (m.get("raw_span") or [0])[0])
        occ = self._occurrences(env, text) if text else {}
        flagged = {}
        def is_flagged(key):
            c = self.cluster(key, lens)
            cid = c["id"] if c else key
            if cid not in flagged:
                flagged[cid] = bool(self.flag_of(c["members"] if c else [key], lens))
            return flagged[cid]
        entities = [{**self._entity_ref(m["key"], lens), "span": m.get("raw_span") or m.get("clean_span"),
                     "key": m["key"], "mention_name": m["name"], "occurrences": occ.get(m["key"], []),
                     "flagged": is_flagged(m["key"])} for m in ms]
        details = []
        for d in env["detail_mentions"]:
            sp = d.get("raw_span") or d.get("clean_span")
            if not sp:
                continue
            t, v = d["detail_type"], d["normalized"]
            owner = f"{note_key}:{d['owner_ref']}" if d.get("owner_ref") not in (None, "UNASSIGNED") else None
            ref = self._entity_ref(owner, lens) if owner in self.mentions else None
            details.append({"type": t, "span": sp, "subtype": d.get("subtype"),
                            "raw": masked_value(t, v) if t in MASKED_TYPES and v else self.redact(d["raw_value"]),
                            "ident": public_ident(t, v) if v else None, "owner": owner,
                            "owner_name": ref["name"] if ref else None, "owner_entity": ref["id"] if ref else None})
        actions = []
        for a in self.actions:
            if a["note"] != note_key or not a["span"]:
                continue
            who = []
            for p in a["participants"]:
                nm = self._entity_ref(p["mention"], lens)["name"] if p["mention"] in self.mentions else "?"
                who.append(f"{nm} ({p['role']})")
            actions.append({"id": a["id"], "type": a["type"], "span": a["span"], "who": who})
        review = env.get("review_items", [])
        return {"kind": "note", "id": note_key, "title": f"Note {n['note_id']}",
                "claim_id": n["claim_id"], "chars": len(text), "text": text,
                "highlight": span, "entities": entities, "details": details, "actions": actions,
                "review_items": review[:50], "review_count": len(review),
                "extraction_error": env.get("extraction_error")}

    def notes_list(self):
        per = defaultdict(int)
        for m in self.mentions.values():
            per[m["note_key"]] += 1
        return [{"id": k, "note_id": str(v["note_id"]), "claim_id": v["claim_id"], "chars": len(v["text"]),
                 "mentions": per.get(k, 0)} for k, v in sorted(self.notes.items())]

    def claim_view(self, claim_id, lens="default"):
        if not any(m["claim_id"] == claim_id for m in self.mentions.values()):
            return None
        seen, ents = set(), []
        for m in sorted(self.mentions.values(), key=lambda m: m["key"]):
            if m["claim_id"] != claim_id:
                continue
            ref = self._entity_ref(m["key"], lens)
            if ref["id"] in seen:
                continue
            seen.add(ref["id"])
            c = self.cluster(m["key"], lens)
            ms = [k for k in (c["members"] if c else [m["key"]]) if self.mentions[k]["claim_id"] == claim_id]
            wl = subtree_weakest(c, ms) if c else None
            ents.append({**ref, "mentions": len(ms), "confidence": wl["p"] if wl else None,
                         "elsewhere": sorted({self.mentions[k]["claim_id"] for k in (c["members"] if c else [])} - {claim_id}),
                         "category": self.category_of.get(m["key"])})
        notes = [{"id": k, "title": f"Note {v['note_id']}", "chars": len(v["text"])}
                 for k, v in sorted(self.notes.items()) if v["claim_id"] == claim_id]
        return {"kind": "claim", "id": claim_id, "title": claim_id, "lens": lens,
                "entities": sorted(ents, key=lambda e: (-e["mentions"], e["name"])), "notes": notes}

    def view(self, kind, ident, lens="default", span=None):
        if kind == "entity":     return self.entity_view(ident, lens)
        if kind == "identifier": return self.identifier_view(ident, lens)
        if kind == "note":       return self.note_view(ident, lens, span)
        if kind == "claim":      return self.claim_view(ident, lens)
        return None

    # ---- search --------------------------------------------------------------------
    def suggest(self, q, limit=6):
        """Typeahead over entities, identifiers, notes and claims. No model involved."""
        qn = _norm(q)
        if not qn:
            return []
        qd = re.sub(r"\D", "", q)
        toks = qn.split()
        out = []
        seen = set()
        pr = self.projection("default")
        for c in pr["clusters"]:
            forms = {f for k in c["members"] for f in self.mentions[k]["forms"]}
            best = 0.0
            for f in forms:
                fn = _norm(f)
                if fn.startswith(qn): best = max(best, 3.0)
                elif all(t in fn.split() or any(w.startswith(t) for w in fn.split()) for t in toks):
                    best = max(best, 2.0)
                elif qn in fn: best = max(best, 1.0)
            if best:
                out.append((best + min(len(c["members"]), 20) / 40, {
                    "kind": "entity", "id": c["id"], "label": self.title_of(c["members"]),
                    "sub": f"{self.mentions[c['id']]['type']} · {len(c['members'])} mention(s) · "
                           f"{len({self.mentions[k]['claim_id'] for k in c['members']})} claim(s)"}))
        for key, recs in self.details_of.items():
            if not key.startswith("id:"):
                continue
            ident = key[3:]
            t, v = ident.split(":", 1)
            raw = recs[0]["raw"]
            hit = (qd and len(qd) >= 3 and qd in re.sub(r"\D", "", v)) or qn in _norm(raw) or qn in _norm(v)
            if hit and ident not in seen:
                seen.add(ident)
                out.append((2.5, {"kind": "identifier", "id": public_ident(t, v), "label": raw,
                                  "sub": f"{t} · {len(recs)} occurrence(s)"}))
        for nk, n in self.notes.items():
            if qn in _norm(nk) or qn == str(n["note_id"]):
                out.append((2.8, {"kind": "note", "id": nk, "label": f"Note {n['note_id']}",
                                  "sub": n["claim_id"]}))
        for claim in sorted({m["claim_id"] for m in self.mentions.values()}):
            if qn in _norm(claim):
                out.append((2.8, {"kind": "claim", "id": claim, "label": claim, "sub": "claim"}))
        out.sort(key=lambda x: -x[0])
        grouped = defaultdict(list)
        for score, s in out:
            if len(grouped[s["kind"]]) < limit:
                grouped[s["kind"]].append({**s, "score": round(score, 2)})
        order = ["entity", "identifier", "claim", "note"]
        return [s for k in order for s in grouped[k]]

    # ---- retrieval for questions ---------------------------------------------------
    def passages(self, question, clusters, width=None, cap=None):
        """[(note, start, end, why)]: windows of source text, deduplicated (overlapping
        windows in one note merge) and capped. First where the question's own words occur
        as a phrase ("no fault attorneys" finds "No-Fault Attorneys"), then around the
        mentions of the chosen parties, strongest first."""
        width, cap = width or PASSAGE_WIDTH, cap or PASSAGE_CAP
        out = []

        def add(note, s, e, why):
            text = self.notes[note]["text"]
            a, b = max(0, s - width), min(len(text), e + width)
            while a > 0 and not text[a - 1].isspace() and s - a < width + 40: a -= 1
            while b < len(text) and not text[b].isspace() and b - e < width + 40: b += 1
            for i, (nn, x, y, w) in enumerate(out):
                if nn == note and a <= y and x <= b:
                    if max(b, y) - min(a, x) <= PASSAGE_MAX:
                        out[i] = (nn, min(a, x), max(b, y), w)
                    return
            if len(out) < cap:
                out.append((note, a, b, why))

        words = [w for w in _norm(question).split() if w not in QUESTION_STOP]
        if 1 <= len(words) <= 6 and (len(words) > 1 or len(words[0]) >= 5):
            rx = re.compile(r"(?<![A-Za-z0-9])" + r"[\W_]{1,3}".join(map(re.escape, words)) + r"(?![A-Za-z0-9])", re.I)
            for nk, n in sorted(self.notes.items()):
                for k, m in enumerate(rx.finditer(n["text"])):
                    if k >= PASSAGES_PER_NOTE:
                        break
                    add(nk, m.start(), m.end(), "the question's words")
        for c in clusters:
            for k in c["members"][:3]:
                m = self.mentions[k]
                sp = m.get("raw_span") or m.get("clean_span")
                if sp and m["note_key"] in self.notes:
                    add(m["note_key"], sp[0], sp[1], f"around {self.title_of(c['members'])}")
        return out

    def retrieve(self, question, lens="default", max_entities=14, max_actions=40, stats=None):
        """A small subgraph relevant to a question: matching entities, one hop out
        through shared actions and cross-claim links, and the actions that connect them.
        Every fact carries a short alias the answer can cite. `stats`, if given, is filled
        with what each step found, for the progress log."""
        stats = {} if stats is None else stats
        qn = set(_norm(question).split()) - QUESTION_STOP
        pr = self.projection(lens)
        scored = []
        for c in pr["clusters"]:
            words = set()
            for k in c["members"]:
                words |= set(_norm(" ".join(self.mentions[k]["forms"])).split())
                for d in self.details_of[k]:
                    words |= set(_norm(d["raw"]).split())
                cat = self.category_of.get(k)
                if cat: words |= set(_norm(f"{cat['value']} {cat.get('subcategory') or ''}").split())
            if flags_for(c["members"], self.wl_by_mention, lens):
                words |= {"flagged", "flag", "review", "watchlist", "excluded", "exclusion", "leie", "oig"}
            hit = len(qn & words)
            if hit:
                scored.append((hit + 0.02 * len(c["members"]), c))
        stats["matched_by_words"] = bool(scored)
        if not scored:   # fall back to the most-mentioned parties
            scored = [(len(c["members"]) / 100, c) for c in pr["clusters"]]
        scored.sort(key=lambda x: -x[0])
        seeds = [c for _, c in scored[:max_entities // 2]]
        stats["seeds"] = [self.title_of(c["members"]) for c in seeds]
        stats["candidates_scored"] = len(scored)
        chosen = {c["id"]: c for c in seeds}
        # one hop: co-participants in actions, strongest first
        hop = defaultdict(int)
        for c in seeds:
            for k in c["members"]:
                for a in self.actions_of[k]:
                    for p in a["participants"]:
                        oc = pr["cluster_of"].get(p["mention"])
                        if oc and oc["id"] not in chosen:
                            hop[oc["id"]] += 1
        for cid, _ in sorted(hop.items(), key=lambda x: -x[1]):
            if len(chosen) >= max_entities: break
            chosen[cid] = pr["cluster_of"][cid]
        stats["hop_candidates"] = len(hop)
        stats["hop_added"] = len(chosen) - len(seeds)
        stats["hop_names"] = [self.title_of(c["members"]) for cid, c in chosen.items()
                              if cid not in {s["id"] for s in seeds}][:8]

        facts, alias = [], {}
        for i, (cid, c) in enumerate(chosen.items(), start=1):
            a = f"e{i}"
            alias[a] = {"kind": "entity", "id": cid, "label": self.title_of(c["members"])}
            dets = sorted({f"{d['type']}={d['raw']}" for k in c["members"] for d in self.details_of[k]})[:6]
            cats = sorted({self.category_of[k]["value"] for k in c["members"] if k in self.category_of})
            claims = sorted({self.mentions[k]["claim_id"] for k in c["members"]})
            conf = c["weakest"]["p"] if c["weakest"] else None
            basis = sorted({e["basis_class"] for e in c["edges"]})
            facts.append(f"[{a}] ENTITY {self.title_of(c['members'])!r} type={self.mentions[cid]['type']} "
                         f"mentions={len(c['members'])} claims={claims} categories={cats} "
                         f"details={dets} merge_confidence={conf} merge_basis={basis or ['single']}")
            for f in self.flag_of(c["members"], lens)[:3]:
                r = f["record"]
                facts.append(f"[{a}] FLAGGED FOR REVIEW at lens {lens}: mention {f['mention_name']!r} links to "
                             f"OIG LEIE exclusion record {r.get('name')!r} ({r.get('general')}, {r.get('specialty')}, "
                             f"{r.get('city')} {r.get('state')}, exclusion type {r.get('excl_type')} on "
                             f"{r.get('excl_date')}) with p={f['p']} basis={f['basis_class']}. A flag is a lead to "
                             f"check, not a finding.")
        # Actions: those touching a chosen party, and those whose own words match the
        # question's ("who referred...", "who billed..."), ranked by both. Without the second,
        # a question about referrals only reached referral actions if their parties happened
        # to be matched by name first.
        qstems = {_stem(w) for w in qn if len(w) > 2}
        acts = []
        ids = set(chosen)
        for a in self.actions:
            parts = [pr["cluster_of"].get(p["mention"]) for p in a["participants"]]
            touch = sum(1 for pc in parts if pc and pc["id"] in ids)
            astems = {_stem(w) for w in _norm(a["type"].replace("_", " ") + " " + a["quote"]).split() if len(w) > 2}
            verb = len(qstems & astems)
            if touch or verb:
                acts.append((touch + 2 * verb, a))
        acts.sort(key=lambda x: -x[0])
        # parties of word-matched actions join the facts, so their citations resolve
        for _, a in acts[:max_actions]:
            for p in a["participants"]:
                pc = pr["cluster_of"].get(p["mention"])
                if pc and pc["id"] not in chosen and len(chosen) < max_entities + 10:
                    chosen[pc["id"]] = pc
                    i = len(alias) + 1
                    while f"e{i}" in alias: i += 1
                    alias[f"e{i}"] = {"kind": "entity", "id": pc["id"], "label": self.title_of(pc["members"])}
                    facts.append(f"[e{i}] ENTITY {self.title_of(pc['members'])!r} type={self.mentions[pc['id']]['type']} "
                                 f"mentions={len(pc['members'])} (reached through an action matching the question)")
        inv = {v["id"]: k for k, v in alias.items()}
        for j, (_, a) in enumerate(acts[:max_actions], start=1):
            al = f"a{j}"
            alias[al] = {"kind": "note", "id": a["note"], "span": a["span"], "label": a["type"]}
            who = []
            for p in a["participants"]:
                pc = pr["cluster_of"].get(p["mention"])
                who.append(f"{inv.get(pc['id'], self.title_of(pc['members']))}({p['role']})" if pc else p["role"])
            facts.append(f"[{al}] ACTION {a['type']} stance={a['stance']} time={a['time']} "
                         f"participants={who} claim={a['claim_id']} quote={a['quote'][:240]!r}")
        stats["actions_found"], stats["actions_sent"] = len(acts), min(len(acts), max_actions)
        n_links = 0
        for l in self.links:
            ca, cb = pr["cluster_of"].get(l["a"]), pr["cluster_of"].get(l["b"])
            if not (ca and cb) or ca["id"] == cb["id"] or l["p"] < 0.1:
                continue
            if ca["id"] in ids and cb["id"] in ids:
                n_links += 1
                facts.append(f"[{inv[ca['id']]}~{inv[cb['id']]}] NOT-MERGED LINK p={l['p']} basis={l['basis_class']} "
                             f"veto={l['veto']} distance={l['distance']}")
        stats["not_merged_links"] = n_links
        # source passages: the text around the question's own words and around the chosen
        # parties' mentions, so the model can read relationships extraction did not capture
        passages = self.passages(question, [c for c in chosen.values()])
        for j, (note, s, e, why) in enumerate(passages, start=1):
            al = f"p{j}"
            alias[al] = {"kind": "note", "id": note, "span": [s, e], "label": "passage"}
            text = re.sub(r"\s+", " ", self.notes[note]["text"][s:e]).strip()
            facts.append(f"[{al}] PASSAGE {note} claim={self.notes[note]['claim_id']} ({why}): {text!r}")
        stats["passages"] = len(passages)
        stats["passage_notes"] = sorted({p[0] for p in passages})
        stats["flag_facts"] = sum(1 for f in facts if " FLAGGED FOR REVIEW " in f)
        stats["facts"] = len(facts)
        return facts, alias
