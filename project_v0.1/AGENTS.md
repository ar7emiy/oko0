# AGENTS.md

Entity intelligence over insurance claim notes. Read this before writing code.

## The goal

Give an investigator — human or AI — a **dossier** for any entity, and let them
research that entity's activity across the whole corpus, where **every statement
traces back to the exact text that produced it.**

The user is a predictive SIU investigator: they flag claims that do not add up,
early. They treat dossiers as investigation notes.

## Hard rules

These are not style preferences. Each one is here because breaking it produced a
measured failure in the previous build. Do not relitigate them without a
measurement.

1. **A name never decides identity.** Names propose candidates; evidence
   decides. *Why: different people score 0.89–0.92 on name similarity. Letting a
   name score drive merges fused four different Andersons into one entity, and
   put 46% of mentions in entities that mixed multiple real people.*

2. **Never ask a model for a character offset, an id, or a closed-vocabulary
   label.** Ask it to quote text and make local judgements. *Why: 100% of the
   surfaces it quotes are verbatim-correct; its offsets are wrong ~2 times in 3;
   its class labels contradict themselves on 30% of identical strings.*

3. **Locate, never trust.** A span is found by searching the document for the
   model's quoted string. If the quote is not found verbatim, **reject the
   row.** *Why: this took span grounding from 33% to 100% at zero recall cost.*

4. **No global transitive merge.** Entities are claim-scoped; cross-claim
   identity is a link. *Why: under transitive closure one bad edge corrupts an
   entire connected component, without bound.*

5. **Anything that must be consistent must be deterministic.** Normalization,
   type-from-name, span location, validation, id assignment. Same input, same
   output, every time.

6. **Declining is a valid output.** `unknown` type, unbound identifier,
   unreviewed link. Never guess to fill a field.

7. **Never overwrite a human decision.** A run may insert `identity_link` rows
   with status `auto` or `review`. It must never modify one that is `accepted`
   or `rejected`.

8. **Report composition, not just totals.** *Why: B-cubed F1 read 0.907 while
   46% of mentions sat in fused entities, and entity count read "42 vs 42 gold"
   because over-merges and fragmentation cancelled. Four separate times an
   aggregate metric preferred a broken system.*

9. **Measure before building.** For anything you would tag *reasoned* or
   *assumed*, run the query first. In the previous build this reversed the
   decision four times and twice removed work entirely.

10. **Record errors in place rather than quietly fixing them.** A wrong claim
    that gets corrected in the open is what makes the rest of the docs
    trustworthy.

## Conventions

- **Python only, no `.ipynb`.** Runnable pipeline steps live in `notebooks/` as
  `# %%` cell-format `.py` files: they run cell-by-cell in an IDE, run
  start-to-finish as scripts, and diff as source.
- **`config/config.py` is the only place** a model name, threshold, seed or path
  is defined. Nothing else hardcodes one.
- **Library code in `src/`, orchestration in `notebooks/`.**
- Comments explain *why*, and cite the measurement where one exists. Do not
  write comments that restate the code.

## Commands

```bash
python notebooks/01_extract.py      # spans -> mentions
python notebooks/02_resolve.py      # local entities + cross-claim links
python notebooks/03_measure.py      # composition metrics vs ground truth
python tests/fast_test.py           # invariants, fixed 60-doc slice
```

## Evaluation

The fixed slice is `CFG.EVAL_SLICE` — `DOC00000`–`DOC00059`, named and fixed on
purpose so numbers stay comparable across runs. Ground truth is the corpus
manifest; the pipeline must never read it (that is leakage, not evaluation).

**The metric that matters is over-merge rate**: what fraction of labeled
mentions sit in a local entity or linked identity containing more than one real
entity. v0 scored **46%**. Beat that or the rebuild has not earned itself.

## What carried over from v0, and what did not

**Carried (measured good):** `textnorm`, `gazetteers` (identifier recall 1.000,
real checksums), `chunking`, the locate-the-quote span fix, the identifier
binding prompt (0.989 precision, declines when unsure), `genai` (cache, backoff,
per-task routing), `runlog`.

**Deleted deliberately:** `entity_class` in every form, global clustering, the
person-name comparison model applied to organizations, fabricated graph edges.

**Not carried:** v0's 34-item defect register. Those describe a system being
replaced. The *lessons* are the rules above; the backlog stays behind.
