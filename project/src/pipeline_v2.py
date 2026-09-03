"""Bridge: Layer 1 (hybrid ensemble) -> the mentions/assertions tables.

This replaces the single-pass extractor as the input to Layer 2 (ER), Layer 3
(graph) and Layer 4 (agent), so the whole stack runs on high-recall output.

Per chunk:  token_ner ∪ gazetteer ∪ llm  ->  sweep  ->  coref  ->  filter  ->  persist

Filtering is where recall-first extraction pays its precision debt. Three guards,
all evidence-based rather than model-based:
  * anaphora are never entities (routed to coref links instead);
  * spans inside a boilerplate/disclaimer segment cannot be NAME entities;
  * a name span must look like a name (no all-caps legalese, no header labels).
Identifier spans (email/phone/npi/tin/ssn/dob/address) become assertions bound to
the nearest preceding name mention, exactly as before, so Layer 2's blocking
passes and Layer 3's shared-identifier edges keep working.

The scan-coverage ledger is still written for every chunk, so the 100%-character
coverage proof survives the architecture change.
"""
from __future__ import annotations

import hashlib

import difflib

import re
from collections import Counter, defaultdict

from . import (chunking, contracts, coref, gazetteers, ner_ensemble, profiling,
               relations, runlog, sweep, textnorm)
from .repository import Repository
from .settings import CFG, Paths

CHUNK_PASS = "L1"

# NER label -> contracts.ENTITY_CLASSES
LABEL_TO_CLASS = {
    "person": "claimant",
    "organization": "medical_provider",
    "medical_provider": "medical_provider",
    "law_firm": "attorney",
    "attorney": "attorney",
    "repair_shop": "repair_shop",
    "adjuster": "adjuster",
    "claimant": "claimant",
}
IDENTIFIER_LABEL_TO_PREDICATE = {
    "email": "has_email", "phone": "has_phone", "npi": "has_npi",
    "tin": "has_tin", "ssn": "has_ssn", "vin": "has_vin", "date": "has_dob",
    "date_written": "has_dob", "address": "has_address",
}
NAME_LABELS = set(LABEL_TO_CLASS)

_ALLCAPS_LEGALESE = re.compile(r"^[A-Z][A-Z\s&'/.-]{6,}$")
_HEADER_LABEL = re.compile(
    r"^(From|Sent|To|Cc|Subject|Date|Claim|Claimant|Clmt|Atty|Attorney|Counsel|"
    r"Provider|Physician|Treating|Mailing|Email|Phone|Address|Contact|Birthdate|"
    r"DOB|NPI|TIN|Direct|Confidentiality|Notice)\b",
    re.I)


def _is_plausible_name(surface: str) -> bool:
    s = surface.strip()
    if len(s) < 3 or "\n" in s:
        return False
    if _ALLCAPS_LEGALESE.match(s):        # CONFIDENTIALITY NOTICE, etc.
        return False
    if _HEADER_LABEL.match(s):            # template/email header labels
        return False
    toks = [t for t in re.split(r"[\s,]+", s) if t]
    if len(toks) < 2 and not s.lower().startswith("dr"):
        return False
    # must contain at least two capitalized alphabetic tokens
    caps = [t for t in toks if t[:1].isupper() and t.strip(".").isalpha()]
    return len(caps) >= 2 or s.lower().startswith("dr")


def span_grounded(raw_text: str, span_start: int, span_end: int, value: str) -> int:
    """1 if `value` fuzzy-locates within the claimed span (with small slack)."""
    if not value:
        return 0
    lo = max(0, span_start - 5)
    hi = min(len(raw_text), span_end + 5)
    window = raw_text[lo:hi].lower()
    v = value.strip().lower()
    if not v:
        return 0
    if v in window:
        return 1
    # sliding fuzzy match
    n = len(v)
    best = 0.0
    for i in range(0, max(1, len(window) - n + 1)):
        best = max(best, difflib.SequenceMatcher(None, v, window[i:i + n]).ratio())
        if best >= CFG.SPAN_FIDELITY_MIN_RATIO:
            return 1
    return 1 if best >= CFG.SPAN_FIDELITY_MIN_RATIO else 0


def _boilerplate_ranges(repo: Repository) -> dict[str, list[tuple[int, float]]]:
    """Per-doc (start, end, score) for disclaimer-ish segments.

    Returns a SCORE, not a verdict. Layer 0 no longer emits a 'boilerplate'
    segment kind: a hard kind meant one misclassified segment silently deleted
    every real name inside it, and a differently-worded disclaimer (the common
    case on real data) excluded nothing at all. The score is attached to the
    mention instead, so a downstream consumer can discount it while the
    evidence stays in the record.
    """
    segs = repo.table("segments")
    out: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    if "boilerplate_score" not in segs.columns:
        return out
    for _, s in segs[segs["boilerplate_score"] > 0].iterrows():
        out[s["doc_id"]].append(
            (int(s["char_start"]), int(s["char_end"]), float(s["boilerplate_score"])))
    return out


def _boilerplate_score_at(pos: int, ranges: list[tuple[int, int, float]]) -> float:
    """Disclaimer-likeness of the segment containing `pos` (0.0 if none)."""
    for (a, b, sc) in ranges:
        if a <= pos < b:
            return sc
    return 0.0


def run(repo: Repository, limit_docs: int | None = None,
        use_llm: bool = True, use_sweep: bool = True,
        doc_ids: list[str] | None = None) -> dict:
    """Run Layer 1 and populate mentions/assertions/scan_ledger.

    `doc_ids` restricts the pass to named notes (the incremental ingest path);
    `limit_docs` takes the first N (a research convenience). Without either this
    is a whole-corpus pass, which is what the backfill wants.
    """
    docs_df = repo.table("documents")
    claim_of = {r["doc_id"]: r["claim_id"] for _, r in docs_df.iterrows()}
    files = profiling.note_files(doc_ids)
    if limit_docs:
        files = files[:limit_docs]
    texts = {f.stem: f.read_text(encoding="utf-8") for f in files}
    doc_map = {d: (claim_of.get(d, "UNKNOWN"), t) for d, t in texts.items()}

    chunks = chunking.chunk_corpus(doc_map)
    token_ner = ner_ensemble.get_token_ner()
    resolver = coref.get_resolver()
    boiler = _boilerplate_ranges(repo)

    # segments give each mention a dup_group_id (quoted-copy handling downstream)
    segs = repo.table("segments")
    seg_by_doc: dict[str, list[dict]] = defaultdict(list)
    for _, s in segs.iterrows():
        seg_by_doc[s["doc_id"]].append(s.to_dict())

    # ---- Layer 1 per chunk ------------------------------------------------
    spans_by_doc: dict[str, list] = defaultdict(list)
    ledger = []
    n_sweep_added = 0
    # Heartbeat: this loop is the slowest thing in the pipeline (a Gemini call
    # per chunk in the LLM lane) and it used to run completely silent. Minutes of
    # no output is indistinguishable from a hang, which is exactly how the
    # pathological .iterrows() in resolution went unnoticed for so long.
    runlog.field("chunks", f"{len(chunks)} across {len(texts)} note(s)")

    # The LLM lane runs FIRST, for every chunk, through genai's thread pool.
    # Calling it inside the per-chunk loop below made it one blocking request at
    # a time with GENAI_MAX_WORKERS=8 idle -- measured on 54 notes, the
    # difference between a couple of minutes and fifteen.
    llm_by_chunk: dict[str, list] = {}
    if use_llm:
        with runlog.stage("llm lane", f"{len(chunks)} chunks, "
                                      f"{CFG.GENAI_MAX_WORKERS} workers"):
            llm_by_chunk = ner_ensemble.llm_extract_chunks(chunks)
            runlog.field("spans", sum(len(v) for v in llm_by_chunk.values()))

    # Token-NER lane, also batched. Same reason as the LLM lane: GLiNER is
    # several times faster over a batch than over one chunk at a time on CPU,
    # and this loop is the only caller that has all the chunks in hand.
    ner_by_chunk: dict[str, list] = {}
    with runlog.stage("token-ner lane", f"{len(chunks)} chunks, {token_ner.name}"):
        batched = token_ner.extract_many([c.text for c in chunks],
                                         [c.char_start for c in chunks])
        ner_by_chunk = {c.chunk_id: sp for c, sp in zip(chunks, batched)}
        runlog.field("spans", sum(len(v) for v in ner_by_chunk.values()))

    # Identifier-binding lane. Gazetteer finds and validates; the LLM says who
    # each identifier belongs to. Only chunks containing identifiers are sent,
    # so this costs far less than one extra call per chunk.
    bindings_by_chunk: dict[str, list] = {}
    if use_llm:
        hits_by_chunk = {c.chunk_id: [h for h in gazetteers.scan(c.text) if h.valid]
                         for c in chunks}
        n_with = sum(1 for v in hits_by_chunk.values() if v)
        if n_with:
            with runlog.stage("binding lane", f"{n_with} of {len(chunks)} chunks "
                                              "contain identifiers"):
                bindings_by_chunk = relations.bind_identifiers_many(
                    chunks, hits_by_chunk)
                n_b = sum(len(v) for v in bindings_by_chunk.values())
                n_named = sum(1 for v in bindings_by_chunk.values()
                              for b in v if b.owner_text)
                runlog.field("bindings", f"{n_b} offered, {n_named} with an owner "
                                         f"({n_b - n_named} declined)")

    for i, ch in enumerate(chunks):
        runlog.every(50, i, len(chunks), f"chunks unioned ({ch.doc_id})")
        spans = ner_ensemble.extract_chunk(ch, token_ner, use_llm=use_llm,
                                           use_gazetteer=True, use_token_ner=True,
                                           llm_spans=llm_by_chunk.get(ch.chunk_id, []),
                                           ner_spans=ner_by_chunk.get(ch.chunk_id, []))
        if use_sweep:
            extra = sweep.sweep_chunk(ch, spans)
            n_sweep_added += len(extra)
            spans = ner_ensemble.union_spans([spans, extra])
        spans_by_doc[ch.doc_id].extend(spans)
        ledger.append(contracts.ScanSpan(ch.doc_id, ch.char_start, ch.char_end,
                                         "layer1_ensemble", CHUNK_PASS).__dict__)

    # ---- per doc: merge, coref, filter, persist ---------------------------
    # Ids are CONTENT-DERIVED, not sequential.
    #
    # A per-run counter restarting at 1 collides the moment a second run inserts
    # into the same database, which is exactly what the incremental ingest path
    # does -- it raised UNIQUE constraint failed on the first arriving note.
    # Seeding the counter past the stored maximum would fix the crash and leave
    # the worse half of the problem: re-processing a note would mint DIFFERENT
    # ids for the same mentions, orphaning every same_as_edges row that
    # referenced the old ones.
    #
    # Hashing (doc_id, span, label) instead makes re-ingesting a note produce
    # byte-identical ids, so a re-ingest is genuinely idempotent and stored
    # edges stay valid. `used` disambiguates the rare true collision rather than
    # letting sqlite reject the batch.
    used: set[str] = set()

    def sid(prefix: str, *parts) -> str:
        h = hashlib.sha1("".join(str(x) for x in parts).encode("utf-8")).hexdigest()
        base = f"{prefix}{h[:12]}"
        if base not in used:
            used.add(base)
            return base
        for i in range(1, 1000):
            alt = f"{base}_{i}"
            if alt not in used:
                used.add(alt)
                return alt
        raise RuntimeError(f"could not mint a unique id for {parts!r}")

    # doc -> [(value_lower, owner_text)] from the binding lane
    bindings_by_doc: dict[str, list] = defaultdict(list)
    for ch in chunks:
        for b in bindings_by_chunk.get(ch.chunk_id, []):
            if b.owner_text:
                bindings_by_doc[ch.doc_id].append((b.value.strip().lower(),
                                                   b.owner_text))

    mentions, assertions, coref_links, id_obs = [], [], [], []
    binding_methods = Counter()
    n_in_boilerplate = n_dropped_shape = 0

    for doc_id in sorted(spans_by_doc):
        raw = texts[doc_id]
        merged = ner_ensemble.union_spans([spans_by_doc[doc_id]])
        merged.sort(key=lambda c: c.start)
        bl = boiler.get(doc_id, [])

        def seg_for(pos: int):
            for s in seg_by_doc.get(doc_id, []):
                if s["char_start"] <= pos < s["char_end"]:
                    return s
            return None

        # 1) name mentions
        doc_mentions = []
        mention_surface: dict[str, str] = {}   # for the binding-lane resolver
        for c in merged:
            if c.label not in NAME_LABELS:
                continue
            boiler_sc = _boilerplate_score_at(c.start, bl)
            if boiler_sc >= 0.5:
                n_in_boilerplate += 1        # counted, NOT dropped
            if not _is_plausible_name(c.text):
                n_dropped_shape += 1
                continue
            seg = seg_for(c.start)
            left = raw[max(0, c.start - 50):c.start]
            right = raw[c.end:min(len(raw), c.end + 70)]
            klass = _classify(c.text, c.label, left, right)
            mid = sid("m", doc_id, c.start, c.end, c.label)
            row = contracts.Mention(
                mention_id=mid, doc_id=doc_id,
                segment_id=seg["segment_id"] if seg else None,
                entity_class=klass, surface=c.text,
                norm_surface=textnorm.normalize_name(c.text),
                char_start=c.start, char_end=c.end,
                extractor="+".join(sorted(c.extractors)),
                dup_group_id=seg.get("dup_group_id") if seg else None,
                inside_quoted=1 if (seg and seg["kind"] == "quoted") else 0,
                boilerplate_score=boiler_sc,
            ).__dict__
            mentions.append(row)
            doc_mentions.append((c.start, mid))
            mention_surface[mid] = c.text
            assertions.append(_assn(
                sid("a", doc_id, mid, "has_name", c.start, c.end),
                mid, "has_name", c.text, c.text, doc_id,
                c.start, c.end, "asserted",
                "+".join(sorted(c.extractors)), raw))

        doc_mentions.sort()

        def subject_for(pos: int):
            """Bind an identifier to a name only on STRONG proximity evidence.

            A loose 'nearest preceding mention anywhere' rule mis-binds across
            email headers and quoted chains ("From: A <a@x>\\nTo: B <b@y>"),
            attaching B's address to A. Those wrong identifiers then look like
            conflicting validated ids and the cluster-consistency rule splits one
            real person into many entities. So we require the name and the
            identifier to sit on the SAME LINE, or on the immediately preceding
            line (the signature-block case: name on one line, contact below).
            No qualifying name -> no assertion, rather than a wrong one.
            """
            line_start = raw.rfind("\n", 0, pos) + 1
            prev_line_start = raw.rfind("\n", 0, max(0, line_start - 1)) + 1
            best = None
            for (s, mid) in doc_mentions:
                if s > pos:
                    break
                if s >= line_start:                 # same line
                    best = mid
                elif s >= prev_line_start and (pos - s) <= 120:
                    best = mid                      # immediately preceding line
            return best

        def llm_binding_for(doc, s_, e_, value):
            """Mention id the binding lane named as this identifier's owner.

            The lane returns an owner NAME; this resolves it to a mention in the
            same document by surface match, preferring the nearest one when a
            name occurs several times. Returns None when the lane declined, when
            it named nobody we extracted, or when the LLM lane is off -- and the
            caller then falls back to line proximity.
            """
            owners = [o for v, o in bindings_by_doc.get(doc, [])
                      if v == (value or "").strip().lower()]
            if not owners:
                return None
            want = {textnorm.normalize_name(o) for o in owners}
            best, best_d = None, 10 ** 9
            for (ms, mid) in doc_mentions:
                m_surf = mention_surface.get(mid, "")
                nm = textnorm.normalize_name(m_surf)
                if not nm:
                    continue
                if any(nm == w or nm in w or w in nm for w in want):
                    d = abs(ms - s_)
                    if d < best_d:
                        best, best_d = mid, d
            return best

        # 2) identifier spans. EVERY identifier is recorded as a first-class
        # observation; binding it to a name is a separate, optional step. An
        # identifier with no name nearby (an orphan) is not noise -- it is the
        # case identifier-mediated resolution exists to solve, and dropping it
        # silently destroyed 100% of them in an earlier build.
        n_unbound = 0
        for c in merged:
            pred = IDENTIFIER_LABEL_TO_PREDICATE.get(c.label)
            if not pred:
                continue
            kind_i = {"has_email": "email", "has_phone": "phone", "has_npi": "npi",
                      "has_tin": "tin", "has_ssn": "ssn", "has_vin": "vin",
                      "has_address": "address",
                      "has_dob": "dob"}.get(pred, c.label)

            # Binding precedence: LLM first, line rule as fallback.
            #
            # Measured against ground truth, the line rule binds one identifier
            # in four to the WRONG party (precision 0.747, recall 0.371), and
            # 144 of the 176 it left unbound had their owner named within 300
            # characters. The LLM reaches 0.973 and declines rather than
            # guessing. So the rule is the fallback now, not the decider --
            # and `binding_method` records which one spoke, per observation,
            # so the mix is measurable rather than assumed.
            subj, method = llm_binding_for(doc_id, c.start, c.end, c.text), "llm"
            if subj is None:
                subj, method = subject_for(c.start), "line_rule"
            if subj is None:
                method = "unbound"

            id_obs.append({
                "doc_id": doc_id, "char_start": c.start, "char_end": c.end,
                "kind": kind_i, "value_raw": c.text,
                "value_norm": textnorm.normalize_identifier(kind_i, c.text),
                "subject_mention_id": subj,
                "binding_method": method,
                "validated": 1 if c.score >= 1.0 else 0,
                "extractor": "+".join(sorted(c.extractors)),
            })
            binding_methods[method] += 1
            if subj is None:
                n_unbound += 1
                continue
            kind = {"has_email": "email", "has_phone": "phone", "has_npi": "npi",
                    "has_tin": "tin", "has_ssn": "ssn"}.get(pred, "text")
            pol = _polarity(raw, c.start, c.end)
            assertions.append(_assn(
                sid("a", doc_id, subj, pred, c.start, c.end),
                subj, pred, c.text,
                textnorm.normalize_identifier(kind, c.text),
                doc_id, c.start, c.end, pol, "gazetteer", raw))

        # 2b) allegation free-text -> assertions (kept separate from facts)
        for am in re.finditer(r"(suspect[^.;\n]*|alleg[^.;\n]*)", raw, re.I):
            subj = subject_for(am.start()) or (doc_mentions[0][1] if doc_mentions else None)
            if subj is None:
                continue
            txt = am.group(0).strip()
            assertions.append(_assn(
                sid("a", doc_id, subj, "allegation", am.start()),
                subj, "allegation", txt, txt.lower(), doc_id,
                am.start(), am.start() + len(txt), "alleged",
                "layer1_ensemble", raw))

        # 3) coreference: anaphora -> antecedent (links, not nodes)
        ment_dicts = [{"start": m["char_start"], "end": m["char_end"],
                       "text": m["surface"], "label": m["entity_class"]}
                      for m in mentions if m["doc_id"] == doc_id]
        mid_by_span = {(m["char_start"], m["char_end"]): m["mention_id"]
                       for m in mentions if m["doc_id"] == doc_id}
        for link in resolver.resolve(raw, ment_dicts):
            coref_links.append({
                "doc_id": doc_id,
                "anaphor_start": link.start, "anaphor_end": link.end,
                "anaphor_text": link.surface, "anaphor_kind": link.kind,
                "antecedent_start": link.antecedent_start,
                "antecedent_end": link.antecedent_end,
                "antecedent_surface": link.antecedent_surface,
                "antecedent_mention_id": mid_by_span.get(
                    (link.antecedent_start, link.antecedent_end)),
                "backend": link.backend, "confidence": link.confidence,
            })

    # ---- persist ----------------------------------------------------------
    repo.conn.execute("PRAGMA foreign_keys=OFF")
    if doc_ids is None:
        # Whole-corpus pass: extraction output is rebuilt, and every resolution
        # artifact downstream of it is invalidated with it.
        for t in ("assertions", "mentions", "scan_ledger", "coref_links",
                  "identifier_observations",
                  "entity_members", "entity_versions",
                  "entity_attributes", "dossiers", "entities"):
            repo.conn.execute(f"DELETE FROM {t}")
    else:
        # Incremental pass: replace only the rows belonging to these notes, so
        # re-ingesting a note is idempotent, and leave every other note's
        # extraction -- and the resolved entities built from it -- untouched.
        # Resolution is updated incrementally instead (entity_resolution
        # .resolve_incremental), not thrown away and rebuilt.
        marks = ",".join("?" for _ in doc_ids)
        repo.conn.execute(
            f"DELETE FROM assertions WHERE source_doc_id IN ({marks})", doc_ids)
        # same_as_edges reference mentions by id. Ids are content-derived, so a
        # re-extraction of the same text reproduces them exactly and the edges
        # stay valid -- but if the extractors changed their minds (a model
        # upgrade, a threshold change), a mention can genuinely disappear, and
        # an edge pointing at a row that no longer exists is worse than no edge.
        # Drop those, and only those.
        # ORDER MATTERS: everything keyed by mention_id has to go before the
        # mentions themselves, or the subquery finds nothing to match against.
        sub = f"SELECT mention_id FROM mentions WHERE doc_id IN ({marks})"
        repo.conn.execute(
            f"DELETE FROM same_as_edges "
            f"WHERE mention_id_a IN ({sub}) OR mention_id_b IN ({sub})",
            list(doc_ids) + list(doc_ids))
        repo.conn.execute(f"DELETE FROM mention_blocks WHERE mention_id IN ({sub})",
                          doc_ids)
        for t in ("mentions", "scan_ledger", "coref_links",
                  "identifier_observations"):
            repo.conn.execute(f"DELETE FROM {t} WHERE doc_id IN ({marks})", doc_ids)
    repo.conn.commit()
    repo.conn.execute("PRAGMA foreign_keys=ON")

    repo.add_mentions(mentions)
    repo.add_assertions(assertions)
    repo.add_scan_spans(ledger)
    repo.add_coref_links(coref_links)
    repo.add_identifier_observations(id_obs)

    return {
        "n_chunks": len(chunks), "n_mentions": len(mentions),
        "n_assertions": len(assertions), "n_coref_links": len(coref_links),
        "n_sweep_added": n_sweep_added,
        "n_identifier_obs": len(id_obs),
        "n_orphan_identifiers": sum(1 for o in id_obs if o["subject_mention_id"] is None),
        "binding_methods": dict(binding_methods),
        # kept and flagged, never dropped -- see _boilerplate_ranges
        "mentions_in_boilerplate": n_in_boilerplate,
        "dropped_shape": n_dropped_shape,
        "token_ner_backend": token_ner.name, "coref_backend": resolver.name,
        "coref_sample": coref_links[:3],
    }


_ADJUSTER_DOMAIN = "@ourinsco.com"


def _classify(surface: str, label: str, left: str, right: str) -> str:
    """Infer entity class from the surface plus BOTH sides of its context.

    Right-context matters: in email headers the discriminating signal (the
    carrier's own domain, the firm name in a signature) follows the name.
    """
    low = surface.lower()
    l, r = left.lower(), right.lower()

    # 1) surface-intrinsic signals are strongest
    if any(w in low for w in ("auto body", "collision", "automotive", "car care",
                              "body works", "repair")):
        return "repair_shop"
    if low.startswith("dr") or any(w in low for w in (
            "orthopedic", "physical therapy", "imaging", "medical group",
            "chiropractic", "neurology", "clinic", "hospital")):
        return "medical_provider"
    if any(w in low for w in ("law group", "llp", "legal", "trial group",
                              "attorneys", "law offices")):
        return "attorney"

    # 2) our own carrier domain on either side -> internal adjuster / client rep
    if _ADJUSTER_DOMAIN in r or _ADJUSTER_DOMAIN in l:
        return "adjuster"
    if "claims department" in r or "adjuster" in l or "claim rep" in l:
        return "adjuster"

    # 3) an external firm domain or firm name following the name -> attorney
    if re.search(r"@(?!ourinsco\.com|example\.com)[a-z0-9.\-]+\.[a-z]{2,}", r):
        return "attorney"
    if any(w in r for w in ("law group", "llp", "legal partners", "trial group",
                            "injury attorneys", "law offices")):
        return "attorney"

    # 4) explicit left-side role cue (template labels: "Clmt Atty - <name>")
    role = gazetteers.role_from_context(left)
    if role:
        return role

    return LABEL_TO_CLASS.get(label, "claimant")


def _polarity(raw: str, s: int, e: int) -> str:
    ctx = raw[max(0, s - 40):e + 10].lower()
    if any(c in ctx for c in ("wrong", "correct is", "prior note listed")):
        return "retracted"
    if any(c in ctx for c in ("suspect", "alleg")):
        return "alleged"
    if any(c in ctx for c in ("denies", "denied", "no ", "not ")):
        return "negated"
    if any(c in ctx for c in ("reported", "per records", "states", "advised")):
        return "reported"
    return "asserted"


def _assn(assertion_id, subj, pred, raw_v, norm_v, doc_id, s, e, pol, extractor, raw_text):
    return contracts.Assertion(
        assertion_id=assertion_id, subject_mention_id=subj, predicate=pred,
        object_value_raw=raw_v, object_value_norm=norm_v, polarity=pol,
        source_doc_id=doc_id, source_span_start=s, source_span_end=e,
        extractor=extractor, pass_id=CHUNK_PASS,
        grounded=span_grounded(raw_text, s, e, raw_v), confidence=0.85,
    ).__dict__
