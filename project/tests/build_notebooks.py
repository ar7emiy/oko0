"""Generate the 9 notebooks/*.ipynb as thin wrappers over the tested src engines.

Run: python tests/build_notebooks.py   (from the project/ directory)
The notebooks contain the actual pipeline calls; src holds the logic. Keeping the
call sites in the notebooks means the leakage guard (which scans notebook source)
is meaningful, while logic stays unit-testable.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks"
NB.mkdir(exist_ok=True)

BOOTSTRAP = (
    "# --- bootstrap: make the src package importable from any working dir ---\n"
    "import sys\n"
    "from pathlib import Path\n"
    "p = Path.cwd().resolve()\n"
    "while not (p / 'config' / '00_config.py').exists() and p != p.parent:\n"
    "    p = p.parent\n"
    "if str(p) not in sys.path:\n"
    "    sys.path.insert(0, str(p))\n"
    "print('project root:', p)\n"
)


def code(src):
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": src}


def md(src):
    return {"cell_type": "markdown", "metadata": {}, "source": src}


def notebook(cells):
    return {
        "cells": cells,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                     "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


def write(name, cells):
    (NB / name).write_text(json.dumps(notebook(cells), indent=1))
    print("wrote", name)


# ---------------------------------------------------------------------------
# 00 — setup & contracts
# ---------------------------------------------------------------------------
write("00_setup_and_contracts.ipynb", [
    md("# 00 · Setup & Contracts\n"
       "Frozen data contracts shared by every stage. This notebook reads the single "
       "config source of truth and prints the schema every other notebook depends on. "
       "It does **not** read ground truth."),
    code(BOOTSTRAP),
    code("from src.settings import CFG, Paths, PROJECT_ROOT, genai_mode\n"
         "from src import contracts\n"
         "Paths.ensure()\n"
         "print('GENAI_MODEL =', CFG.GENAI_MODEL)\n"
         "print('EMBED_MODEL =', CFG.EMBED_MODEL, '| dim', CFG.EMBED_DIM)\n"
         "print('SEED        =', CFG.SEED)\n"
         "print('GenAI mode  =', genai_mode(), '(offline = deterministic stub; online = Gemini)')\n"),
    code("print('ENTITY_CLASSES:', contracts.ENTITY_CLASSES)\n"
         "print('SEGMENT_KINDS :', contracts.SEGMENT_KINDS)\n"
         "print('POLARITIES    :', contracts.POLARITIES)\n"
         "print('PREDICATES    :', contracts.PREDICATES)\n"
         "print('GEN_PASSES    :', contracts.GEN_PASSES)\n"),
    code("print('Relational schema (SQLite DDL):')\n"
         "print(contracts.DDL)\n"
         "print('tables:', contracts.TABLE_NAMES)\n"),
    code("import json\n"
         "print('extraction_schema  ='); print(json.dumps(contracts.extraction_schema(), indent=1)[:900])\n"
         "print('adjudication_schema='); print(json.dumps(contracts.adjudication_schema(), indent=1))\n"
         "print('query_plan_schema  ='); print(json.dumps(contracts.query_plan_schema(), indent=1)[:900])\n"),
])

# ---------------------------------------------------------------------------
# 01 — generate corpus (ground-truth WRITER)
# ---------------------------------------------------------------------------
write("01_generate_corpus.ipynb", [
    md("# 01 · Generate Synthetic Corpus  ·  ground-truth WRITER\n"
       "Deterministically generates ~1.5–3k legacy claim notes across ~300 claims and, "
       "**in the same pass**, writes the sealed ground-truth manifest with the exact "
       "char offset of every planted mention. Then seals sha256 of every raw note. "
       "After this notebook the raw corpus is read-only for the rest of the pipeline."),
    code(BOOTSTRAP),
    code("from src import corpus_gen\n"
         "from src.hashing import write_hashes, verify_hashes\n"
         "summary = corpus_gen.generate_corpus()\n"
         "print('corpus summary:', summary)\n"),
    code("# seal hashes (written once) and immediately verify\n"
         "hashes = write_hashes(overwrite=True)\n"
         "report = verify_hashes('post-generation')\n"
         "print('sealed', len(hashes), 'raw files; integrity ok =', report['ok'])\n"),
    code("# peek at one raw note and validate a few planted offsets are byte-accurate\n"
         "import json\n"
         "from src.settings import Paths\n"
         "man = json.loads(Paths.manifest_json.read_text())\n"
         "doc = man['documents'][0]['doc_id']\n"
         "print('--- sample note', doc, '---')\n"
         "print((Paths.raw_notes / f'{doc}.txt').read_text()[:700])\n"
         "ok = 0\n"
         "for pl in man['placements'][:2000]:\n"
         "    t = (Paths.raw_notes / f\"{pl['doc_id']}.txt\").read_text()\n"
         "    ok += (t[pl['char_start']:pl['char_end']] == pl['surface_variant'])\n"
         "print('planted-offset fidelity (first 2000):', ok, '/ 2000')\n"
         "print('entities:', len(man['entities']), '| placements:', len(man['placements']),\n"
         "      '| non_entities:', len(man['non_entities']))\n"),
])

# ---------------------------------------------------------------------------
# 02..06 — pipeline
# ---------------------------------------------------------------------------
write("02_profiling.ipynb", [
    md("# 02 · Profiling\n"
       "Ingest raw notes (claim id + category derived from text only — never from the "
       "manifest), segment every note into fully-tiling spans, fingerprint template "
       "blocks, and detect near-duplicates (MinHash over 5-word shingles)."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src import profiling\n"
         "repo = Repository()\n"
         "repo.reset()   # fresh DB for a full pipeline run\n"
         "print('profiling:', profiling.run(repo))\n"),
    code("segs = repo.table('segments')\n"
         "print('segment kinds:'); print(segs['kind'].value_counts())\n"
         "print('template fingerprints:', segs['template_fingerprint'].nunique())\n"
         "print('non-canonical near-dups:', int((segs['is_canonical_dup']==0).sum()))\n"
         "repo.close()\n"),
])

write("03_extraction.ipynb", [
    md("# 03 · Extraction\n"
       "Deterministic per-fingerprint template parsing + narrative/email extraction "
       "(Gemini online / deterministic heuristic offline). Every assertion carries span "
       "offsets, polarity and dates; the span-fidelity validator marks off-span values "
       "grounded=0; the scan-coverage ledger records every span each extractor processed."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src import extraction\n"
         "repo = Repository()\n"
         "print('extraction:', extraction.run(repo))\n"),
    code("ass = repo.table('assertions'); men = repo.table('mentions')\n"
         "print('mentions by class:'); print(men['entity_class'].value_counts())\n"
         "print('predicates:'); print(ass['predicate'].value_counts())\n"
         "print('polarities:'); print(ass['polarity'].value_counts())\n"
         "print('grounded fraction:', round((ass['grounded']==1).mean(), 4))\n"
         "repo.close()\n"),
])

write("04_embed_index.ipynb", [
    md("# 04 · Embed & Index\n"
       "Per-mention node text (normalized name + class + local context) is embedded "
       "(Gemini EMBED_MODEL online / deterministic hashing embedding offline) and indexed "
       "**only** through the VectorStore interface (FAISS IndexFlatIP) with sidecar metadata."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src import embed_index\n"
         "repo = Repository()\n"
         "print('embed_index:', embed_index.run(repo))\n"
         "repo.close()\n"),
])

write("05_resolution.ipynb", [
    md("# 05 · Resolution\n"
       "Unioned blocking passes → weighted-feature scoring (hub down-weighting, gt-free "
       "calibration proxy) → capped adjudicator on the ambiguous band → greedy correlation "
       "clustering (igraph) honoring cannot-link + cluster-scope identifier consistency. "
       "Membership is versioned; mentions are never physically merged."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src import resolution\n"
         "repo = Repository()\n"
         "res = resolution.run(repo)\n"
         "print('resolution:', {k: v for k, v in res.items() if k != 'calibration'})\n"
         "print('calibration proxy:', res['calibration'])\n"),
    code("ent = repo.table('entities')\n"
         "print('resolved entities by class:'); print(ent['entity_class'].value_counts())\n"
         "cp = repo.table('candidate_pairs')\n"
         "print('candidate-pair bands:'); print(cp['band'].value_counts())\n"
         "repo.close()\n"),
])

write("06_profiles_dossiers.ipynb", [
    md("# 06 · Profiles & Dossiers\n"
       "Bitemporal attribute rows with survivorship tiers (validated-ID > template > "
       "narrative); retractions close known_to; conflicts flagged. Builds a dossier per "
       "entity where every evidence item has a table-derived machine_annotation."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src import profiles\n"
         "repo = Repository()\n"
         "print('profiles:', profiles.run(repo))\n"),
    code("import json\n"
         "d = repo.all_dossiers()[0]\n"
         "print('sample dossier:', d['canonical_name'], '[', d['class'], ']')\n"
         "print('  identity   :', d['identity'])\n"
         "print('  attributes :', list(d['attribute_timelines'].keys()))\n"
         "print('  #evidence  :', len(d['evidence']))\n"
         "if d['evidence']:\n"
         "    print('  ex machine_annotation:', d['evidence'][0]['machine_annotation'])\n"),
    code("# dump bulk tables to parquet (SQLite is the single file; parquet for bulk)\n"
         "paths = repo.dump_parquet()\n"
         "print('parquet bulk tables written:', [p.name for p in paths])\n"
         "repo.close()\n"),
])

# ---------------------------------------------------------------------------
# 07 — audit (ground-truth READER)
# ---------------------------------------------------------------------------
write("07_audit_vs_ground_truth.ipynb", [
    md("# 07 · Audit vs Ground Truth  ·  the ONLY pipeline reader of ground truth\n"
       "Joins pipeline outputs to the sealed manifest and reports honestly, misses "
       "included: entity counts + mapping, mention recall/precision with itemized misses, "
       "B-cubed cluster quality with over/under-merge evidence trails, the scan-coverage "
       "proof, and hash re-verification."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src import audit\n"
         "repo = Repository()\n"
         "report = audit.run(repo)\n"
         "print(report['summary'])\n"),
    code("m = report['entity_mapping']\n"
         "print('GT entities            :', m['gt_entity_count'])\n"
         "print('system clusters        :', m['system_entity_count'])\n"
         "print('GT never recovered     :', m['n_gt_never_recovered'])\n"),
    code("r = report['mention_recall']; p = report['mention_precision']\n"
         "print('mention recall  :', r['recall'], '(', r['found'], '/', r['total_placements'], ')')\n"
         "print('mention precision:', p['precision'], '| planted non-entities wrongly extracted:', p['fp_nonentity_planted'])\n"
         "print('recall by segment_kind:'); \n"
         "import json; print(json.dumps(r['by_segment_kind'], indent=1))\n"
         "print('recall by hard case:'); print(json.dumps(r['by_hard_case'], indent=1))\n"
         "print('sample misses (doc_id, span, variant):')\n"
         "for miss in r['missed_sample'][:8]: print('  ', miss['doc_id'], miss['span'], repr(miss['surface_variant']), miss['segment_kind'])\n"),
    code("c = report['cluster_quality']\n"
         "print('B-cubed  precision/recall/F1:', c['bcubed_precision'], c['bcubed_recall'], c['bcubed_f1'])\n"
         "print('over-merges:', c['n_over_merges'], '| under-merges:', c['n_under_merges'])\n"
         "print('over-merge evidence trail (sample):')\n"
         "import json\n"
         "for om in report['over_merge_evidence'][:2]: print(json.dumps(om, indent=1)[:700])\n"),
    code("cov = report['coverage_proof']\n"
         "print('SCAN-COVERAGE PROOF')\n"
         "print('  overall coverage     :', cov['overall_coverage'])\n"
         "print('  docs at 100%%         :', cov['n_docs_full_coverage'], '/', cov['n_docs'])\n"
         "print('  coverage histogram   :', cov['coverage_histogram'])\n"
         "print('  overlap depth (chars):', cov['overlap_depth_chars'], '(fraction', cov['overlap_fraction'], ')')\n"
         "print('  docs under 100%%      :', cov['n_docs_under_100pct'])\n"
         "print('hash re-verification  :', report['hash_verification']['ok'])\n"
         "repo.close()\n"),
])

# ---------------------------------------------------------------------------
# 08 — lookup & query app
# ---------------------------------------------------------------------------
write("08_lookup_app.ipynb", [
    md("# 08 · Lookup & Query App\n"
       "Name search + NL questions. Gemini (offline: deterministic parser) translates a "
       "question into a STRUCTURED query plan; deterministic code executes it over the "
       "tables (the LLM plans, the tables answer). Dossiers render with clickable evidence "
       "that highlights the exact span in the raw note. A static HTML snapshot is exported."),
    code(BOOTSTRAP),
    code("import os, json\n"
         "from src.repository import Repository\n"
         "from src import app\n"
         "repo = Repository()\n"
         "index = app.EntityIndex(repo)\n"
         "print('dossiers indexed:', len(index.dossiers))\n"),
    code("# run the preloaded example questions: show the generated plan + table-executed answer\n"
         "for q in app.EXAMPLE_QUESTIONS:\n"
         "    out = app.answer_question(repo, index, q)\n"
         "    names = [index.dossiers[e]['canonical_name'] for e in out['result']['entity_ids'][:3]]\n"
         "    print('Q:', q)\n"
         "    print('   plan   :', json.dumps(out['plan']))\n"
         "    print('   answer : n =', out['result']['n'], '| top:', names)\n"
         "    print()\n"),
    code("# export a self-contained clickable-evidence dossier snapshot\n"
         "eid = max(index.dossiers, key=lambda e: index.dossiers[e]['n_mentions'])\n"
         "path = app.export_dossier_html(repo, eid)\n"
         "print('exported dossier snapshot ->', path)\n"
         "print('open this file in a browser: click any evidence item to jump to the highlighted span.')\n"),
    code("# launch the Gradio app (skipped automatically under headless orchestration)\n"
         "import os\n"
         "if os.environ.get('LAUNCH_APP', '1') != '0':\n"
         "    demo = app.build_app(repo)\n"
         "    demo.launch(share=False)\n"
         "else:\n"
         "    print('LAUNCH_APP=0 -> skipping interactive launch (headless run).')\n"),
])

# ---------------------------------------------------------------------------
# 09 — orchestration
# ---------------------------------------------------------------------------
write("09_run_all.ipynb", [
    md("# 09 · Run All  ·  fresh-VM orchestration\n"
       "Installs deps, echoes config, seals+verifies corpus hashes, runs the mechanical "
       "leakage / model / faiss / storage guards, executes notebooks 01–08 in order "
       "(papermill-style via nbconvert), re-verifies hashes, prints the audit summary, and "
       "checks the acceptance checklist. Target: < ~40 min on Colab."),
    code("# 1) install dependencies (Colab). Safe to re-run.\n"
         "import sys, subprocess, os\n"
         "req = os.path.join(os.getcwd(), 'requirements.txt')\n"
         "if os.path.exists(req):\n"
         "    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', req])\n"
         "else:\n"
         "    print('requirements.txt not found in', os.getcwd(), '- run from project/ root')\n"),
    code(BOOTSTRAP),
    code("# 2) echo config (single source of truth)\n"
         "from src.settings import CFG, Paths, genai_mode\n"
         "Paths.ensure()\n"
         "print('GENAI_MODEL=%s  EMBED_MODEL=%s  SEED=%s  mode=%s' % (CFG.GENAI_MODEL, CFG.EMBED_MODEL, CFG.SEED, genai_mode()))\n"),
    code("# 3) run notebook 01 first (writes corpus + seals hashes)\n"
         "import os, sys, subprocess\n"
         "from pathlib import Path\n"
         "ROOT = Path.cwd()\n"
         "NBDIR = ROOT / 'notebooks'\n"
         "os.environ['LAUNCH_APP'] = '0'   # headless: do not block on Gradio\n"
         "\n"
         "def run_nb(name):\n"
         "    # papermill-style execution in a FRESH kernel process (no nesting)\n"
         "    subprocess.run([sys.executable, '-m', 'nbconvert', '--to', 'notebook',\n"
         "                    '--execute', '--inplace', '--ExecutePreprocessor.timeout=2400',\n"
         "                    str(NBDIR / name)], check=True, cwd=str(ROOT),\n"
         "                   env={**os.environ, 'LAUNCH_APP': '0'})\n"
         "    print('  ran', name)\n"
         "\n"
         "run_nb('01_generate_corpus.ipynb')\n"),
    code("# 4) mechanical guards (hard-fail the run on any violation)\n"
         "from src.hashing import verify_hashes\n"
         "from src import leakage_guard\n"
         "start_hashes = verify_hashes('run-all START')\n"
         "print('corpus integrity at start:', start_hashes['ok'])\n"
         "guards = leakage_guard.run_all_guards()\n"
         "print('leakage guard      :', guards['ground_truth_leakage']['ok'])\n"
         "print('model isolation    :', guards['model_isolation']['ok'])\n"
         "print('faiss isolation    :', guards['faiss_isolation']['ok'])\n"
         "print('storage isolation  :', guards['storage_isolation']['ok'])\n"),
    code("# 5) execute the pipeline notebooks 02-08 in order\n"
         "for name in ['02_profiling.ipynb','03_extraction.ipynb','04_embed_index.ipynb',\n"
         "             '05_resolution.ipynb','06_profiles_dossiers.ipynb',\n"
         "             '07_audit_vs_ground_truth.ipynb','08_lookup_app.ipynb']:\n"
         "    run_nb(name)\n"),
    code("# 6) re-verify hashes at END and print the audit summary block\n"
         "end_hashes = verify_hashes('run-all END')\n"
         "from src.repository import Repository\n"
         "from src import audit\n"
         "repo = Repository(); report = audit.run(repo)\n"
         "print('\\n==================== AUDIT SUMMARY ====================')\n"
         "print(report['summary'])\n"
         "print('======================================================\\n')\n"),
    code("# 7) ACCEPTANCE CHECKLIST\n"
         "cov = report['coverage_proof']; cq = report['cluster_quality']\n"
         "checks = []\n"
         "checks.append(('Corpus hashes identical before/after', start_hashes['ok'] and end_hashes['ok']))\n"
         "checks.append(('Leakage guard passes', guards['ground_truth_leakage']['ok']))\n"
         "checks.append(('Scan coverage 100%% per doc (or listed)', cov['n_docs_under_100pct']==0))\n"
         "checks.append(('Audit: counts + recall + B-cubed + over/under-merge', True))\n"
         "checks.append(('NL question -> plan -> table answer (nb 08 ran)', True))\n"
         "checks.append(('Model in config only; FAISS behind VectorStore; storage behind repo',\n"
         "               guards['model_isolation']['ok'] and guards['faiss_isolation']['ok'] and guards['storage_isolation']['ok']))\n"
         "for label, ok in checks:\n"
         "    print(('[x]' if ok else '[ ]'), label)\n"
         "assert all(ok for _, ok in checks), 'ACCEPTANCE CHECKLIST FAILED'\n"
         "print('\\nAll acceptance checks passed.')\n"
         "repo.close()\n"),
    code("# 8) launch the app (interactive; skip in headless CI by setting LAUNCH_APP=0)\n"
         "import os\n"
         "os.environ['LAUNCH_APP'] = '1'\n"
         "from src.repository import Repository\n"
         "from src import app\n"
         "repo = Repository()\n"
         "print('Launch the lookup app with:')\n"
         "print('    from src import app; app.build_app(repo).launch(share=True)')\n"
         "# app.build_app(repo).launch(share=True)   # uncomment in Colab\n"),
])

print("\nAll notebooks written to", NB)


# ===========================================================================
# Layer 1-4 architecture notebooks (10-13)
# ===========================================================================
write("10_layer1_hybrid_extraction.ipynb", [
    md("# 10 · Layer 1 — Hybrid High-Recall Extraction\n"
       "Overlapping chunking → coreference → **union** of (token-NER ∪ gazetteer ∪ LLM) "
       "→ pass-2 differential sweep. The premise is that a single LLM pass misses "
       "low-salience entities; this notebook shows each component and writes the "
       "result into the mentions/assertions tables that Layers 2–4 consume."),
    code(BOOTSTRAP),
    code("from src import chunking, gazetteers, coref, ner_ensemble, sweep\n"
         "from src.settings import CFG, Paths\n"
         "print('chunk target:', CFG.CHUNK_TOKENS, 'tokens, overlap', CFG.CHUNK_OVERLAP_RATIO)\n"
         "doc = sorted(Paths.raw_notes.glob('*.txt'))[1]\n"
         "text = doc.read_text()\n"
         "chunks = chunking.chunk_document(doc.stem, 'CLM0000', text)\n"
         "print('chunks:', len(chunks), '| coverage:', chunking.coverage_report(text, chunks))\n"),
    code("# deterministic gazetteers: structured codes are never left to the LLM\n"
         "for h in gazetteers.scan_valid(text):\n"
         "    print(f'  {h.label:16s} {h.text!r}')\n"),
    code("# token-level NER: reads every literal token, regardless of salience\n"
         "backend = ner_ensemble.get_token_ner()\n"
         "print('backend:', backend.name, '(GlinerBackend activates when gliner is installed)')\n"
         "for c in backend.extract(text, 0)[:10]:\n"
         "    print(f'  {c.label:18s} {c.text!r}')\n"),
    code("# the UNION + sweep, with provenance showing which extractor found each span\n"
         "spans = ner_ensemble.extract_chunk(chunks[0], backend)\n"
         "extra = sweep.sweep_chunk(chunks[0], spans)\n"
         "allspans = ner_ensemble.union_spans([spans, extra])\n"
         "for c in allspans[:14]:\n"
         "    print(f'  {c.label:16s} {c.text!r:34s} found_by={sorted(c.extractors)}')\n"
         "print('\\nresidual unmapped after sweep:', sweep.residual_report(text, allspans))\n"),
    code("# coreference: pronouns/descriptors are LINKS, never graph nodes\n"
         "demo = 'Dr. Ruiz treated the claimant. Ace Collision billed us. '\\\n"
         "       'The shop inflated parts and the physician disagreed.'\n"
         "ms = [{'start': demo.index('Dr. Ruiz'), 'end': demo.index('Dr. Ruiz')+8,\n"
         "       'text': 'Dr. Ruiz', 'label': 'medical_provider'},\n"
         "      {'start': demo.index('Ace Collision'), 'end': demo.index('Ace Collision')+13,\n"
         "       'text': 'Ace Collision', 'label': 'repair_shop'}]\n"
         "for l in coref.get_resolver().resolve(demo, ms):\n"
         "    print(f'  {l.kind:10s} {l.surface!r:16s} -> {l.antecedent_surface!r} ({l.antecedent_class})')\n"),
    code("# run Layer 1 over the whole corpus into mentions/assertions\n"
         "from src.repository import Repository\n"
         "from src import pipeline_v2\n"
         "repo = Repository()\n"
         "print(pipeline_v2.run(repo))\n"
         "print('\\nmention provenance:'); print(repo.table('mentions')['extractor'].value_counts())\n"
         "repo.close()\n"),
])

write("11_recall_ablation.ipynb", [
    md("# 11 · Recall Ablation — does the union actually approach zero misses?\n"
       "The architecture's central claim, measured against the sealed ground-truth "
       "manifest. Cumulative stages: LLM only → +token-NER → +gazetteer → +sweep. "
       "This notebook reads ground truth and is therefore an AUDIT-side notebook."),
    code(BOOTSTRAP),
    code("from src import ablation\n"
         "report = ablation.run()          # full corpus; pass limit_docs=250 for a fast pass\n"
         "print(report['summary'])\n"),
    code("print(f\"{'stage':16s} {'name_recall':>11s} {'lift':>8s} {'name_prec':>10s} {'id_recall':>10s}\")\n"
         "for stage, sc in report['stages'].items():\n"
         "    lift = sc.get('recall_lift')\n"
         "    lift = f'{lift:+.3f}' if lift is not None else '     -'\n"
         "    print(f\"{stage:16s} {sc['recall']:>11.4f} {lift:>8s} \"\n"
         "          f\"{sc['name_span_precision']:>10.3f} {sc['identifiers']['identifier_recall']:>10.4f}\")\n"),
    code("final = report['stages']['plus_sweep']\n"
         "print('identifier recall by kind:')\n"
         "for k, v in final['identifiers']['by_kind'].items():\n"
         "    print(f\"   {k:10s} {v['recall']:.3f}  ({v['found']}/{v['total']})\")\n"
         "print('\\nwhich extractor covered each found placement:')\n"
         "for combo, n in list(final['provenance_of_found'].items())[:8]:\n"
         "    print(f'   {combo:28s} {n}')\n"),
    code("print('remaining misses after the full stack:', final['n_missed'])\n"
         "for m in final['missed_sample'][:10]:\n"
         "    print('  ', m['doc_id'], m['span'], repr(m['surface']), m['segment_kind'])\n"
         "print('\\nchunking:', report['chunking'])\n"),
])

write("12_layer3_scoped_graph.ipynb", [
    md("# 12 · Layer 3 — Dual Storage (chunk vectors + claim-scoped graph)\n"
       "Every node and edge carries a `claim_id`; the predicate schema is a "
       "whitelist of domain verbs and generic edges are rejected at insert time. "
       "Cross-claim network links live in a reserved scope reachable only through "
       "a separately-authorized API."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src import build_graph\n"
         "from src.graph_store import get_graph_store, validate_predicate, PredicateRejected\n"
         "repo = Repository()\n"
         "stats = build_graph.build_graph(repo)\n"
         "print({k: v for k, v in stats.items() if k != 'predicates'})\n"
         "print('predicates:', stats['predicates'])\n"),
    code("# graph density control: generic predicates are rejected outright\n"
         "for p in ('TREATED_BY', 'MENTIONED_IN', 'RELATED_TO'):\n"
         "    try:\n"
         "        print(f'  {p:14s} -> accepted as {validate_predicate(p)}')\n"
         "    except PredicateRejected as e:\n"
         "        print(f'  {p:14s} -> REJECTED: {str(e)[:70]}')\n"),
    code("g = get_graph_store(); g.load()\n"
         "sub = g.subgraph('CLM0005')\n"
         "print('CLM0005 subgraph:', len(sub['nodes']), 'nodes,', len(sub['edges']), 'edges')\n"
         "for e in sub['edges'][:8]:\n"
         "    print(f\"   {e['subject'][:26]:28s} --{e['predicate']:22s}--> {e['object'][:24]:26s} \"\n"
         "          f\"[{e['doc_id']}:{e['span'][0]}-{e['span'][1]}]\")\n"),
    code("# cross-claim links exist but are NOT reachable from a claim scope\n"
         "from src.graph_store import ScopeViolation, CROSS_CLAIM_SCOPE\n"
         "try:\n"
         "    g.neighbors([], 1, CROSS_CLAIM_SCOPE)\n"
         "except ScopeViolation as e:\n"
         "    print('blocked as designed:', str(e)[:90])\n"
         "try:\n"
         "    g.cross_claim_links(['x'], authorized=False)\n"
         "except ScopeViolation as e:\n"
         "    print('blocked as designed:', str(e)[:90])\n"
         "repo.close()\n"),
])

write("13_layer4_agent.ipynb", [
    md("# 13 · Layer 4 — Per-Claim Agentic Retrieval\n"
       "Hard claim filter → scoped vector entry → 1–2 hop graph expansion → grounded "
       "synthesis with span citations. Includes the scope-isolation proof: the agent "
       "is structurally incapable of reading another claim's data."),
    code(BOOTSTRAP),
    code("from src.repository import Repository\n"
         "from src.agent import ClaimScopedAgent, test_scope_isolation\n"
         "repo = Repository()\n"
         "agent = ClaimScopedAgent(repo)\n"
         "res = agent.answer('CLM0005', 'who represents the claimant and which providers treated them?')\n"
         "print('SCOPE:', res['scope'])\n"
         "print('\\nparties:', [(e['name'], e['class']) for e in res['entities']][:8])\n"
         "print('triples retrieved:', len(res['triples']))\n"
         "print('\\nANSWER:\\n', res['answer'])\n"
         "print('\\ncitations:', res['citations'][:5])\n"),
    code("# every retrieval step, shown\n"
         "chunks = agent.retrieve_chunks('CLM0005', 'attorney representation and treatment')\n"
         "print('step 2 — scoped vector entry:')\n"
         "for c in chunks:\n"
         "    print(f\"   {c['chunk_id']}  claim={c['claim_id']}  score={c['score']}\")\n"
         "eids = agent.entities_in_chunks('CLM0005', chunks)\n"
         "print('\\nstep 3 — entities in those chunks:', len(eids))\n"
         "for t in agent.expand('CLM0005', eids)[:8]:\n"
         "    print(f\"   {t['subject'][:24]:26s} --{t['predicate']:20s}--> {t['object'][:22]}\")\n"),
    code("# SCOPE ISOLATION PROOF\n"
         "iso = test_scope_isolation(agent, 'CLM0005', 'CLM0006')\n"
         "for k, v in iso.items():\n"
         "    print(f'  {k:34s} {v}')\n"
         "assert iso['isolation_holds'], 'SCOPE ISOLATION FAILED'\n"
         "print('\\nscope isolation holds.')\n"),
    code("# escalated cross-claim view (fraud network) — separately authorized\n"
         "ents = [e['entity_id'] for e in res['entities']]\n"
         "links = agent.cross_claim_network(ents, authorized=True)\n"
         "print('cross-claim links for these entities:', len(links))\n"
         "for l in links[:5]:\n"
         "    print(f\"   {l['subject'][:22]:24s} --{l['predicate']:24s}--> {l['object'][:22]:24s}\")\n"
         "    print(f\"      subject claims: {l['claims_of_subject'][:4]}  object claims: {l['claims_of_object'][:4]}\")\n"
         "repo.close()\n"),
])
