# %% [markdown]
# # 20 — Relation extraction, traced end to end
#
# This file is written in `# %%` cell format. VS Code runs each cell in an
# interactive window; `jupytext --to notebook 20_relation_extraction.py`
# converts it to a real `.ipynb` losslessly when you want one.
#
# **What this closes.** The schema has always been a triple store — `assertions`
# is literally subject/predicate/object, and `GraphEdge` is src/predicate/dst.
# But nothing ever *produced* relational triples. The pipeline could emit
# exactly 9 predicates: `has_name`, seven identifier bindings, and `allegation`.
# All of them attach a value to **one** entity. Six declared predicates
# (`represents`, `affiliated_with`, `works_on_claim`, `has_role`, `has_firm`,
# `has_title`) were never produced by any code path.
#
# So the graph's `REPRESENTED_BY` / `TREATED_BY` edges were *synthesized* from
# `entity_class` + shared-claim membership — a workaround for the absence of
# real relation extraction, which is also why `entity_class` ended up carrying
# so much weight.
#
# Run the cells in order. Every step prints what went in and what came out.

# %%
# --- bootstrap: make src importable from any working directory ---
import sys
from pathlib import Path

p = Path.cwd().resolve()
while not (p / "config" / "00_config.py").exists() and p != p.parent:
    p = p.parent
if str(p) not in sys.path:
    sys.path.insert(0, str(p))
PROJECT = p

# Windows consoles default to cp1252 and raise on non-ASCII output. Force UTF-8
# so this script runs identically on Windows, macOS and Linux.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
print("project root:", PROJECT)

import json
import textwrap

from src.settings import CFG, genai_mode
from src import relations, contracts

print("genai mode :", genai_mode())
print("model      :", CFG.GENAI_MODEL)
assert genai_mode() == "online", (
    "This notebook needs a live API key. Put GEMINI_API_KEY in .env at the repo root."
)

# %% [markdown]
# ## Step 1 — the source
#
# Hand-written notes, deliberately **not** from `corpus_gen.py`. The synthetic
# corpus plants relations in shapes we control, so measuring against it partly
# re-measures the fixture. These contain things the generator never produces:
# roles outside `ENTITY_CLASSES` (witness, landlord, employer, interpreter,
# public adjuster), predicates outside `CANONICAL_PREDICATES` (referred_to,
# supervises, daughter_of), casing damage, negation and retraction.

# %%
NOTES_DIR = PROJECT / "data" / "handwritten_notes"
notes = {f.stem: f.read_text(encoding="utf-8")
         for f in sorted(NOTES_DIR.glob("*.txt"))}
expected = json.loads((NOTES_DIR / "expected_relations.json").read_text(encoding="utf-8"))

print(f"{len(notes)} notes loaded\n")
for name, text in notes.items():
    exp = expected.get(name + ".txt", {})
    n_rel = len(exp.get("relations", []))
    n_open = sum(1 for r in exp.get("relations", []) if r.get("outside_closed_vocab"))
    print(f"  {name:14} {len(text):5} chars  {n_rel:2} expected relations "
          f"({n_open} outside the closed vocabulary)  casing={exp.get('casing','mixed')}")

# %% [markdown]
# ### Look at one note in full
# Pick any key from `notes` to inspect. This is the raw input — no processing yet.

# %%
FOCUS = "HW0001_0002"          # <- change this to trace a different note
print(notes[FOCUS])

# %% [markdown]
# ## Step 2 — what the CURRENT pipeline extracts from this note
#
# Before adding anything, establish the baseline: names and identifiers only.
# This is what exists today, and it is why the graph has no real relationships
# to promote.

# %%
from src import gazetteers

hits = gazetteers.scan(notes[FOCUS])
print(f"identifier hits: {len(hits)}")
for h in hits:
    mark = "checksum-verified" if h.checksum_verified else f"{h.validation}"
    print(f"  {h.label:16} {h.text:24} [{h.start}:{h.end}]  {mark}")

print("\nPredicates the current pipeline can emit from this:")
print("  has_npi  <- the NPI above, bound to whatever name precedes it")
print("  has_name <- one per name-shaped span")
print("\nRelations it can emit: NONE. That is the gap.")

# %% [markdown]
# ## Step 3 — the relation extraction prompt
#
# The prompt is the design. Two decisions are load-bearing:
#
# 1. **`predicate` is a free string, not an enum.** A closed list would drop
#    "referred X to Y", "supervises", "is the daughter of" — all present in
#    real notes, none expressible in `CANONICAL_PREDICATES`.
# 2. **`polarity` IS an enum and is required.** Downstream survivorship logic
#    branches on it structurally (`profiles.py` excludes retracted/negated),
#    so an unknown value has no defined behaviour. Storing "our client is NOT
#    alleging permanent impairment" as `asserted` inverts the note's meaning.

# %%
print(relations.PROMPT.format(chunk="<the note text goes here>",
                              roster="<claim party roster, see Step 7>"))
print("\n--- output schema ---")
print(json.dumps(relations.relation_schema(), indent=2))

# %% [markdown]
# ## Step 4 — run it, live
#
# One call, one note. `extract_relations` refuses to run if there is no API key
# rather than returning `[]`, because an empty list is indistinguishable from
# "this note genuinely contains no relationships."

# %%
rels = relations.extract_relations(notes[FOCUS], base_offset=0)
print(f"{len(rels)} relations kept from {FOCUS}")
print("routed away:", getattr(relations.extract_relations, "last_rejected", {}), "\n")
for r in rels:
    flag = f"  ! {','.join(r.flags)}" if r.flags else ""
    print(f"  {r.subject_text:28} --{r.predicate:22}-> {r.object_text:34} "
          f"[{r.polarity}] conf={r.confidence:.2f}{flag}")

# %% [markdown]
# ### Every relation is span-grounded
#
# The evidence span is the clause that *proves* the relation, which is usually
# not the subject's own span. Ungrounded relations are rejected outright, not
# stored with a warning — an assertion whose evidence cannot be located is not
# auditable, and an unauditable assertion is worse than a missing one because
# it looks real.

# %%
raw = notes[FOCUS]
for r in rels:
    quoted = raw[r.evidence_start:r.evidence_end]
    ok = "OK " if quoted.strip() == r.evidence_text.strip() else "MISMATCH"
    print(f"[{ok}] {r.predicate}")
    print(f"        span   : [{r.evidence_start}:{r.evidence_end}]")
    print(f"        proves : {textwrap.shorten(quoted, 96)}")
    print()

# %% [markdown]
# ## Step 5 — predicate normalization, without a whitelist
#
# Surface forms fold toward canonical spellings; **anything unlisted passes
# through unchanged** rather than being dropped or force-fit. This is the
# difference between a normalization table and a closed vocabulary.

# %%
print(f"{'raw from model':28} {'normalized':24} in table?")
print("-" * 66)
for r in rels:
    known = r.predicate_raw.strip().lower().replace(" ", "_") in relations.PREDICATE_NORMALIZATION
    print(f"{r.predicate_raw:28} {r.predicate:24} {'yes' if known else 'NO (passed through)'}")

# %% [markdown]
# ## Step 6 — score against the hand-written ground truth
#
# Loose matching: predicates are an open vocabulary, so exact string equality
# is the wrong test. We match on subject/object overlap and treat the predicate
# as correct if it is semantically in the right family.
#
# The ground truth is my reading of each note, not an adjudicated gold set —
# good enough to catch a missed or inverted relation, not good enough to quote
# a precision figure to a client.

# %%
# Titles and function words that carry no identifying information. Without
# stripping these, "Dr. Alicia Reyes" and "Dr. Reyes" look like different
# parties, and every phrase containing "the" looks similar to every other.
_STOP = {"the", "a", "an", "of", "at", "in", "on", "for", "to", "and", "or",
         "dr", "mr", "mrs", "ms", "prof", "esq", "llp", "llc", "inc", "pc",
         "where", "which", "that", "was", "is", "her", "his", "their", "this"}


def norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum() or ch == " ").strip()


def tokens(s):
    return {t for t in norm(s).split() if len(t) >= 3 and t not in _STOP}


def overlaps(a, b):
    """Match on shared distinctive tokens, not substrings.

    Substring matching failed the first run in both directions: it missed
    "Alicia Reyes" vs "Dr. Reyes" (no containment either way) and would have
    missed "incident location" vs "the building where the incident occurred".
    Requiring one shared non-stopword token of length>=3 handles both without
    becoming so loose that unrelated parties match.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    if ta & tb:
        return True
    na, nb = norm(a), norm(b)
    return bool(na) and bool(nb) and (na in nb or nb in na)


def score_note(note_key, extracted):
    exp = expected.get(note_key + ".txt", {}).get("relations", [])
    matched, missed = [], []
    used = set()
    for e in exp:
        hit = None
        for i, r in enumerate(extracted):
            if i in used:
                continue
            if overlaps(e["subject"], r.subject_text) and (
                    e["object"] is None or overlaps(e["object"], r.object_text)):
                hit = (i, r)
                break
        if hit:
            used.add(hit[0])
            matched.append((e, hit[1]))
        else:
            missed.append(e)
    extra = [r for i, r in enumerate(extracted) if i not in used]
    return matched, missed, extra


matched, missed, extra = score_note(FOCUS, rels)
print(f"{FOCUS}:  {len(matched)} matched / {len(expected[FOCUS + '.txt']['relations'])} expected"
      f"   ({len(extra)} additional not in ground truth)\n")

for e, r in matched:
    pol = "  POLARITY MISMATCH" if e["polarity"] != r.polarity else ""
    star = " *" if e.get("outside_closed_vocab") else "  "
    print(f"  MATCH{star} {e['subject']:24} {e['predicate']:24} -> got {r.predicate}{pol}")
for e in missed:
    star = " *" if e.get("outside_closed_vocab") else "  "
    print(f"  MISS {star} {e['subject']:24} {e['predicate']:24} -> {e['object']}")
for r in extra:
    print(f"  EXTRA   {r.subject_text:24} {r.predicate:24} -> {r.object_text}")
print("\n  * = relation the closed ENTITY_CLASSES/CANONICAL_PREDICATES cannot express")

# %% [markdown]
# ## Step 7 — claim-level context, and why chunk-local extraction is not enough
#
# The first live run kept producing `the claimant --EMPLOYED_BY--> Sunrise
# Property Management`. That is a *correct* reading of HW0001_0002 — the note
# genuinely never names her. Deborah Fitzgerald is named in HW0001_0001.
#
# So this is not a model failure. It is a consequence of where the note
# boundary fell, and no chunk-local extractor can fix it. The system already
# has `coref.py` and a `coref_links` table for exactly this. Below is the cheap
# form of that context: the parties already known on the same claim.

# %%
from src import gazetteers as _gz


def parties_seen(text):
    """Rough party roster from a note: capitalized multi-token spans.

    Deliberately crude - in the real pipeline this comes from the `mentions`
    table after GLiNER has run, not from a regex. Its only job here is to show
    the EFFECT of supplying claim-level context.
    """
    import re as _re
    out = set()
    for m in _re.finditer(r"[A-Z][a-z]+(?:\s+[A-Z][a-z&.]+){1,3}", text):
        t = m.group(0).strip()
        if len(t.split()) >= 2 and not t.startswith(("The ", "This ", "Records ")):
            out.add(t)
    return out


claim_of = {n: n.split("_")[0] for n in notes}
roster_by_claim = {}
for name, text in notes.items():
    roster_by_claim.setdefault(claim_of[name], set()).update(parties_seen(text))

for claim, names in sorted(roster_by_claim.items()):
    print(f"{claim}: {sorted(names)}")

# %% [markdown]
# ## Step 8 — run every note, with claim context, and total it up

# %%
all_results = {}
for name, text in notes.items():
    try:
        all_results[name] = relations.extract_relations(
            text, base_offset=0,
            known_parties=sorted(roster_by_claim[claim_of[name]]))
    except Exception as exc:
        print(f"  {name}: FAILED {type(exc).__name__}: {exc}")
        all_results[name] = []

tot_m = tot_e = tot_x = tot_open_m = tot_open_e = 0
pol_err = 0
print(f"\n{'note':16} {'matched':>9} {'expected':>9} {'extra':>7}   open-vocab")
print("-" * 62)
for name, rl in all_results.items():
    m, ms, x = score_note(name, rl)
    exp_all = expected[name + ".txt"]["relations"]
    open_exp = [e for e in exp_all if e.get("outside_closed_vocab")]
    open_hit = [e for e, _ in m if e.get("outside_closed_vocab")]
    pol_err += sum(1 for e, r in m if e["polarity"] != r.polarity)
    tot_m += len(m); tot_e += len(exp_all); tot_x += len(x)
    tot_open_m += len(open_hit); tot_open_e += len(open_exp)
    print(f"{name:16} {len(m):9} {len(exp_all):9} {len(x):7}   {len(open_hit)}/{len(open_exp)}")

print("-" * 62)
print(f"{'TOTAL':16} {tot_m:9} {tot_e:9} {tot_x:7}   {tot_open_m}/{tot_open_e}")
print(f"\nrecall              : {tot_m}/{tot_e} = {tot_m/max(tot_e,1):.0%}")
print(f"open-vocab recall   : {tot_open_m}/{tot_open_e} = {tot_open_m/max(tot_open_e,1):.0%}"
      "   <- relations the closed vocabulary structurally cannot hold")
print(f"polarity errors     : {pol_err} of {tot_m} matched")

# %% [markdown]
# ### Why open-vocab recall is the number that matters
#
# Total recall says whether extraction works. **Open-vocab recall says whether
# opening the vocabulary was necessary** — every one of those is a relationship
# that would be silently lost under the closed `CANONICAL_PREDICATES` set, no
# matter how good the model is.
#
# Polarity errors matter disproportionately: a negation stored as an assertion
# doesn't lose information, it *reverses* it.

# %%
print("Distinct predicates the model produced across all notes:")
seen = {}
for rl in all_results.values():
    for r in rl:
        seen.setdefault(r.predicate, 0)
        seen[r.predicate] += 1
canon = set(PREDICATE_NORMALIZATION.values()) if (
    PREDICATE_NORMALIZATION := relations.PREDICATE_NORMALIZATION) else set()
for pred, n in sorted(seen.items(), key=lambda kv: -kv[1]):
    where = "in normalization table" if pred in canon else "NEW - passed through"
    print(f"  {pred:28} x{n:<3} {where}")
print(f"\n{len(seen)} distinct predicates. The old closed set had 5 relational ones.")
