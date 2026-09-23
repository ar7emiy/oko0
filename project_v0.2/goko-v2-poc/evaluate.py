"""Score a court-corpus run against the clerk's docket party lists.

    python evaluate.py poc_output/courtlistener

Reads the run's mentions.json, links.json and envelope_*.json, and the gold file
corpus/courtlistener/gold/docket_parties.json. The pipeline never reads the gold
file (AGENTS.md rule 13), so these numbers measure it rather than echo it.

Three questions, each with its denominator stated:

1. Party recall, per docket and per lane. Of the parties the clerk entered, how many
   did the LLM name, and how many did GLiNER find. Only recall: the documents also
   name judges, lawyers and non-parties, so "mentions that are not parties" is not
   an error count.
2. Cross-claim identity, per lens. Five parties are named on both dockets. At each
   lens, how many of those five end up in one cluster spanning both claims, and how
   many cross-claim merges join mentions of two different gold parties. Merges of
   mentions that match no gold party are reported as unscored, not as errors.
3. What the links rest on. For each of the five, the best cross-claim link: its
   probability, basis, and how the names agreed.
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from goko.projection import LENSES, project   # noqa: E402

GOLD = HERE / "corpus" / "courtlistener" / "gold" / "docket_parties.json"
DROP = {"p", "c", "pc", "inc", "llc", "d", "o", "m", "md", "do", "the", "a", "dr", "mr",
        "ms", "mrs", "defendant", "defendants", "plaintiff", "plaintiffs", "esq", "jr", "sr"}


def key_tokens(name):
    return frozenset(w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if w not in DROP)


def gold_parties(gold):
    """{claim: [(party label, [token sets for each d/b/a part])]}, John Does dropped."""
    out = {}
    for claim, g in gold["dockets"].items():
        out[claim] = [(p, [key_tokens(x) for x in re.split(r"\bd/b/a\b", p, flags=re.I)])
                      for p in g["parties"] if not re.match(r"john does?\b", p, re.I)]
    return out


def match_party(name, parties):
    """The gold party a surface name refers to, or None when it matches none or several.

    A name matches when its words are all words of one of the party's names: "Pierre"
    and "Bradley Pierre" both match "Bradley Pierre"; "Nexray" matches the Nexray
    d/b/a. Matching several parties is ambiguous and left unmapped."""
    toks = key_tokens(name)
    if not toks:
        return None
    hits = {label for label, parts in parties if any(toks <= p for p in parts)}
    return hits.pop() if len(hits) == 1 else None


def cross_identity_of(label, claim, gold):
    for i, x in enumerate(gold["cross_claim_identities"]):
        if label in x["by_claim"].get(claim, []):
            return i
    return None


def main(run_dir):
    run = Path(run_dir)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    parties = gold_parties(gold)
    mentions = json.loads((run / "mentions.json").read_text(encoding="utf-8"))
    links = json.loads((run / "links.json").read_text(encoding="utf-8"))
    envelopes = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run.glob("envelope_*.json"))]
    by_key = {m["key"]: m for m in mentions}
    report = {"run": str(run), "gold": str(GOLD.relative_to(HERE))}

    # ---- 1. party recall by lane -------------------------------------------------------
    print("1. PARTY RECALL (denominator: parties on the docket, John Does excluded)")
    recall = {}
    for claim, plist in parties.items():
        llm = {match_party(n, plist) for m in mentions if m["claim_id"] == claim
               for n in m["forms"]}
        gl = set()
        for e in envelopes:
            if e["claim_id"] != claim:
                continue
            gl |= {match_party(c["text"], plist) for c in e["entity_candidates"]}
            gl |= {match_party(m.get("name") or m["quote"], plist) for m in e["entity_mentions"]
                   if "gliner" in m.get("detected_by", [])}
        gliner_ran = any(e["entity_candidates"] or any("gliner" in m.get("detected_by", [])
                                                         for m in e["entity_mentions"])
                         for e in envelopes if e["claim_id"] == claim)
        labels = [p for p, _ in plist]
        recall[claim] = {"parties": labels,
                         "llm_found": sorted(p for p in labels if p in llm),
                         "gliner_found": sorted(p for p in labels if p in gl) if gliner_ran else None}
        r = recall[claim]
        print(f"  {claim}  ({gold['dockets'][claim]['case']})")
        print(f"    LLM     {len(r['llm_found'])}/{len(labels)}")
        print(f"    GLiNER  " + (f"{len(r['gliner_found'])}/{len(labels)}" if gliner_ran else "not run"))
        for p in labels:
            print(f"      {'L' if p in r['llm_found'] else '.'}"
                  f"{'G' if gliner_ran and p in r['gliner_found'] else '.'}  {p}")
    report["party_recall"] = recall

    # ---- 2. cross-claim identity by lens -----------------------------------------------
    n_true = len(gold["cross_claim_identities"])
    ident = {}
    for m in mentions:
        label = match_party(m["name"], parties.get(m["claim_id"], []))
        ident[m["key"]] = cross_identity_of(label, m["claim_id"], gold) if label else None
        m["_gold_party"] = label
    print(f"\n2. CROSS-CLAIM IDENTITY (denominator: {n_true} parties named on both dockets)")
    by_lens = {}
    for lens in LENSES:
        pr = project(list(by_key), links, lens)
        found, wrong, unscored = set(), [], 0
        for c in pr["clusters"]:
            claims = defaultdict(list)
            for k in c["members"]:
                claims[by_key[k]["claim_id"]].append(k)
            if len(claims) < 2:
                continue
            ids_by_claim = {cl: {ident[k] for k in ks if ident[k] is not None} for cl, ks in claims.items()}
            common = set.intersection(*ids_by_claim.values()) if all(ids_by_claim.values()) else set()
            found |= common
            labels = {by_key[k]["_gold_party"] for k in c["members"] if by_key[k]["_gold_party"]}
            if len(labels) > 1:
                wrong.append(sorted(labels))
            if not labels:
                unscored += 1
        by_lens[lens] = {"found": len(found), "of": n_true,
                         "found_names": [gold["cross_claim_identities"][i]["names"][0] for i in sorted(found)],
                         "clusters_joining_different_parties": wrong,
                         "unscored_cross_clusters": unscored}
        x = by_lens[lens]
        print(f"  {lens:<8} found {x['found']}/{n_true}   wrong joins {len(wrong)}   "
              f"unscored cross-claim clusters {unscored}")
        for w in wrong:
            print(f"           WRONG: {w}")
    report["cross_claim"] = by_lens

    # ---- 3. what the true links rest on ------------------------------------------------
    print("\n3. BEST CROSS-CLAIM LINK FOR EACH TRUE IDENTITY")
    best = []
    for i, x in enumerate(gold["cross_claim_identities"]):
        cands = [l for l in links if ident.get(l["a"]) == i and ident.get(l["b"]) == i
                 and by_key[l["a"]]["claim_id"] != by_key[l["b"]]["claim_id"]]
        b = max(cands, key=lambda l: l["p"], default=None)
        row = {"identity": x["names"][0], "cross_links": len(cands)}
        if b:
            row.update({"p": b["p"], "basis_class": b["basis_class"], "veto": b["veto"],
                        "name_agreement": b["name_agreement"],
                        "names": [by_key[b["a"]]["name"], by_key[b["b"]]["name"]],
                        "co_party_overlap": b["co_party"]["overlap"]})
        best.append(row)
        if b:
            ov = b["co_party"]["overlap"] or {}
            print(f"  {x['names'][0]:<44} p={b['p']:<7} {b['basis_class']:<10} "
                  f"{b['name_agreement']}  co-parties {ov.get('matched')}/{ov.get('of')}"
                  + (f"  VETO {b['veto']}" if b["veto"] else ""))
        else:
            print(f"  {x['names'][0]:<44} no cross-claim link proposed")
    report["true_identity_links"] = best

    (run / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwritten to {run / 'evaluation.json'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "poc_output/courtlistener")
