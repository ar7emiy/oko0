# Entity intelligence over claim notes

Builds a **dossier** for every party in a corpus of insurance claim notes — who
they are, what identifies them, what they did, and where they appear — with
every statement traceable to the exact text that produced it.

Built for a predictive SIU investigator: someone flagging claims that do not add
up, early, who treats dossiers as investigation notes.

## Status

Early rebuild. Scaffolding and the carried-over extraction layer are in place;
the identity layer is not written yet. **See `STATE.md`** for exactly where
things stand and what is next.

This is `v0.1`, a deliberate restart of `../project`. That build's extraction
worked well (identifier recall 1.000, span grounding 100%, binding precision
0.940) but its identity layer put **46% of mentions into entities that fused two
or more different real people**. The rebuild keeps what measured well and
replaces what did not. `ARCHITECTURE.md` explains the design; the full
first-principles derivation is in
`../project/designs/rebuild-from-first-principles.md`.

## Layout

```
AGENTS.md          rules for anyone (human or AI) working in this repo -- read first
ARCHITECTURE.md    the design, and the measurements behind each decision
STATE.md           where we left off, what is next, what is still unknown
config/config.py   the ONLY place a model, threshold, seed or path is defined
src/               library code
notebooks/         runnable pipeline steps, `# %%` cell-format .py (never .ipynb)
tests/             invariants over a fixed 60-document slice
```

## Running it

Requires a Gemini API key. A missing key is a broken environment, not a mode —
every model lane raises rather than substituting a stub. Set `GENAI_MODE=offline`
to opt into the research stubs deliberately.

```bash
export GEMINI_API_KEY=...            # or put it in .env at the repo root

python notebooks/01_extract.py       # spans -> mentions
python notebooks/02_resolve.py       # local entities + cross-claim links
python notebooks/03_measure.py       # composition metrics vs ground truth
python tests/fast_test.py            # invariants
```

Notebooks are plain `.py` using `# %%` cells: run them cell-by-cell in VS Code
or PyCharm, run them start-to-finish as scripts, and diff them as source.

## The corpus

Shared with `../project` so both builds can be measured head to head on the same
fixed 60-document slice (`CFG.EVAL_SLICE`). Point `CORPUS_DIR` elsewhere for a
different corpus.

## The one number that matters

**Over-merge rate** — what fraction of mentions land in an entity containing more
than one real party. v0 scored 46%.

Aggregate scores are not the headline here, deliberately: B-cubed F1 read 0.907
on that same 46%-broken system, and preferred the broken configuration in three
separate experiments. Report composition.
