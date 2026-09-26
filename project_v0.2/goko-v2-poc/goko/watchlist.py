""""Flagged for review": what a watchlist link means at a lens.

The notebook links corpus mentions to watchlist records (OIG LEIE) with the same
scorer it uses between mentions, and writes every such link, with its probability,
basis and any veto, to watchlist_links.json. This module decides, at read time,
which of those links an entity shows. The notebook's dossiers and the search app
both call it, so they cannot disagree about who is flagged.

The rule: an entity is Flagged for review at a lens when any of its member
mentions has a watchlist link that lens admits (goko.projection.admits: no veto,
p at or above the lens minimum, and at the strict lens an identifier basis). A
flag is a lead for a person to check, never a finding: most rest on a name alone,
and the basis travels with the flag.
"""
from goko.projection import admits


def flags_for(members, links_by_mention, lens):
    """Admitted watchlist links for a set of mentions, strongest first."""
    out = [l for k in members for l in links_by_mention.get(k, ()) if admits(l, lens)]
    return sorted(out, key=lambda l: (-l["p"], l["b"]))


def near_flags(members, links_by_mention, lens, floor=0.01):
    """Watchlist links this lens does not admit but a reader may want to see: the ones
    a looser lens would admit, or that a veto or basis rule kept out."""
    shown = {id(l) for l in flags_for(members, links_by_mention, lens)}
    out = [l for k in members for l in links_by_mention.get(k, ())
           if id(l) not in shown and (l["p"] >= floor or l.get("veto"))]
    return sorted(out, key=lambda l: (-l["p"], l["b"]))
