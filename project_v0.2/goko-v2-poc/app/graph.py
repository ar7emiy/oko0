"""An in-memory, read-only view of one pipeline run.

Loads what the notebook wrote (mentions.json, links.json, envelope_*.json,
dossier_*.json, run_info.json) plus the note texts, and answers the questions
the interface asks: what matches this text, what is this entity at this lens,
where is this identifier, what does this note say, what is relevant to this
question. Merged entities come from goko.projection, the same code the
notebook's dossiers use, so the app can never show a merge the notebook would
not make.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

from goko.projection import LENSES, project, subtree_weakest

EXCERPT = 180          # characters of context either side of a span


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


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

        # details and actions indexed by owning mention
        self.details_of = defaultdict(list)
        self.detail_owners = defaultdict(set)
        self.actions = []
        for env in self.envelopes:
            nk = env["note_key"]
            for d in env["detail_mentions"]:
                span = d.get("raw_span") or d.get("clean_span")
                rec = {"type": d["detail_type"], "value": d["normalized"], "raw": d["raw_value"],
                       "basis": d.get("basis"), "note": nk, "span": span,
                       "checksum": d.get("checksum"), "detected_by": d.get("detected_by")}
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
                    "type": a["action_type"], "quote": a["quote"], "stance": a.get("stance"),
                    "time": a.get("time_qualifier"), "span": a.get("raw_span") or a.get("clean_span"),
                    "participants": [{"mention": f"{nk}:{p['mention_id']}", "role": p["role"]}
                                     for p in a["participants"]]})
        self.actions_of = defaultdict(list)
        for a in self.actions:
            for p in a["participants"]:
                self.actions_of[p["mention"]].append(a)
        self.links_of = defaultdict(list)
        for l in self.links:
            self.links_of[l["a"]].append(l); self.links_of[l["b"]].append(l)
        # categories from the frozen claim dossiers, per mention
        self.category_of = {}
        for d in self.dossiers.values():
            for e in d["entities"]:
                for k in e["merge_provenance"]["members"]:
                    self.category_of[k] = {"value": e["category"]["value"],
                                           "subcategory": e.get("subcategory"),
                                           "claim_entity": e["entity_id"]}
        self._proj = {}

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

    def _entity_ref(self, key, lens):
        c = self.cluster(key, lens)
        members = c["members"] if c else [key]
        return {"kind": "entity", "id": c["id"] if c else key, "name": self.title_of(members),
                "type": self.mentions[key]["type"]}

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

        folded = {}
        for k in members:
            for d in self.details_of[k]:
                f = folded.setdefault((d["type"], d["value"]), {
                    "type": d["type"], "value": d["value"], "raw": d["raw"], "basis": d["basis"],
                    "checksum": d["checksum"], "evidence": [],
                    "shared_with": []})
                f["evidence"].append(self.excerpt(d["note"], d["span"]))
        for f in folded.values():
            others = {o for o in self.detail_owners[f"{f['type']}:{f['value']}"] if o and o not in members}
            f["shared_with"] = sorted({json.dumps(self._entity_ref(o, lens)) for o in others})
            f["shared_with"] = [json.loads(x) for x in f["shared_with"]]

        acts, related = [], {}
        for k in members:
            for a in self.actions_of[k]:
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
        refused = [r for r in self.projection(lens)["refused"]
                   if r["link"]["a"] in members or r["link"]["b"] in members]
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
            "categories": sorted({json.dumps(self.category_of[k]) for k in members if k in self.category_of}),
            "members": mem, "details": list(folded.values()), "actions": acts,
            "related": sorted(related.values(), key=lambda r: -r["count"]),
            "not_merged": list(best.values())[:12],
            "refused": [{"reason": r["reason"], "a": r["link"]["a"], "b": r["link"]["b"]} for r in refused],
        }

    def identifier_view(self, ident, lens="default"):
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
        return {"kind": "identifier", "id": ident, "title": recs[0]["raw"], "detail_type": t,
                "value": v, "lens": lens, "claims": claims,
                "holders": list(holders.values()),
                "unassigned": sum(1 for r in recs if not r["owner"]),
                "suspicion": shared["suspicion"] if shared else None,
                "distance": shared["distance"] if shared else None,
                "evidence": [self.excerpt(r["note"], r["span"]) for r in recs]}

    def note_view(self, note_key, lens="default", span=None):
        n = self.notes.get(note_key)
        if not n:
            return None
        ms = sorted((m for m in self.mentions.values() if m["note_key"] == note_key),
                    key=lambda m: (m.get("raw_span") or [0])[0])
        env = next(e for e in self.envelopes if e["note_key"] == note_key)
        return {"kind": "note", "id": note_key, "title": f"Note {n['note_id']}",
                "claim_id": n["claim_id"], "chars": len(n["text"]), "text": n["text"],
                "highlight": span,
                "entities": [{**self._entity_ref(m["key"], lens), "span": m.get("raw_span")} for m in ms],
                "review_items": env.get("review_items", [])[:50],
                "extraction_error": env.get("extraction_error")}

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
                out.append((2.5, {"kind": "identifier", "id": ident, "label": raw,
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
    def retrieve(self, question, lens="default", max_entities=14, max_actions=40):
        """A small subgraph relevant to a question: matching entities, one hop out
        through shared actions and cross-claim links, and the actions that connect them.
        Every fact carries a short alias the answer can cite."""
        qn = set(_norm(question).split()) - {"the", "a", "an", "of", "and", "or", "is", "are", "was",
                                             "who", "what", "which", "how", "did", "does", "do", "in",
                                             "on", "to", "for", "with", "by", "at", "any", "all", "there"}
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
            hit = len(qn & words)
            if hit:
                scored.append((hit + 0.02 * len(c["members"]), c))
        if not scored:   # fall back to the most-mentioned parties
            scored = [(len(c["members"]) / 100, c) for c in pr["clusters"]]
        scored.sort(key=lambda x: -x[0])
        seeds = [c for _, c in scored[:max_entities // 2]]
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
        acts = []
        ids = set(chosen)
        for a in self.actions:
            parts = [pr["cluster_of"].get(p["mention"]) for p in a["participants"]]
            if any(pc and pc["id"] in ids for pc in parts):
                acts.append((sum(1 for pc in parts if pc and pc["id"] in ids), a))
        acts.sort(key=lambda x: -x[0])
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
        for l in self.links:
            ca, cb = pr["cluster_of"].get(l["a"]), pr["cluster_of"].get(l["b"])
            if not (ca and cb) or ca["id"] == cb["id"] or l["p"] < 0.1:
                continue
            if ca["id"] in ids and cb["id"] in ids:
                facts.append(f"[{inv[ca['id']]}~{inv[cb['id']]}] NOT-MERGED LINK p={l['p']} basis={l['basis_class']} "
                             f"veto={l['veto']} distance={l['distance']}")
        return facts, alias
