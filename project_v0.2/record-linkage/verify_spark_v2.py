"""Validate Spark v2 without changing notebook settings or running production inputs.

    python verify_spark_v2.py           # memory regressions + comparison parity
    python verify_spark_v2.py --full    # all embedded B1 tests (Spark/fork tests skip locally)

This runner exercises the disk-backed reference path. It does not start Spark or
claim to validate Databricks, RDD scheduling, Unity Catalog access, or Delta writes.
Enable RUN_SELF_TESTS in the notebook on a small synthetic cluster run for those.
"""
import ast
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE / "goko_record_linkage_mvp_b1_spark_v2.ipynb"


def load_definitions():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf8"))
    sources = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    original = json.loads((HERE / 'goko_record_linkage_mvp_b1.ipynb').read_text(encoding='utf8'))
    def core_cells(book):
        return [''.join(c['source']) for c in book['cells'] if c['cell_type'] == 'code'
                and ''.join(c['source']).startswith('# ---- Matching core')]
    if core_cells(original) != core_cells(notebook):
        raise AssertionError('v2 matching core differs from the supplied pandas source')
    for index, source in enumerate(sources):
        ast.parse("\n".join(line for line in source.splitlines() if not line.startswith("%")),
                  filename=f"{NOTEBOOK.name}:code_cell_{index}")
    namespace = {"__name__": "spark_v2_validation", "__file__": str(NOTEBOOK)}
    import types
    module = types.ModuleType(namespace["__name__"])
    sys.modules[module.__name__] = module
    namespace = module.__dict__
    namespace["__file__"] = str(NOTEBOOK)
    definitions = True
    for source in sources:
        if source.startswith("# ---- Settings:"):
            definitions = False
        if source.startswith("# Libraries"):
            continue
        if source.startswith("# ---- Spark: the same tasks"):
            # Spark APIs are imported only on the cluster; definitions below remain parseable.
            source = source.replace("from pyspark.broadcast import Broadcast", "class Broadcast: pass")
            source = source.replace("from pyspark import cloudpickle as _cloudpickle", "import cloudpickle as _cloudpickle")
        if definitions or source.startswith("import unittest, tempfile, io"):
            exec(compile(source, str(NOTEBOOK), "exec"), namespace)
    return namespace


def pool_suite(namespace):
    # Exercise wave ordering and broadcast cleanup through serialized task closures.
    # This transport harness does not stand in for a real Spark integration test.
    exec("def _pool_task(t):\n    if t < 0: raise ValueError('injected task failure')\n    return t * _SHARED['factor'][0], _IN_WORKER and (_SHARED['factor'] is _SHARED.get('alias', _SHARED['factor']))\n", namespace)

    class FakeBroadcast:
        def __init__(self, value):
            self.value, self.destroyed = value, False
        def destroy(self, blocking=False):
            self.destroyed = True

    class FakeRDD:
        def __init__(self, data, fn=None):
            self.data, self.fn = data, fn
        def mapPartitions(self, fn):
            return FakeRDD(self.data, fn)
        def toLocalIterator(self, prefetchPartitions=False):
            for group in self.data:
                fn = namespace['_cloudpickle'].loads(namespace['_cloudpickle'].dumps(self.fn))
                yield from fn(iter([group]))

    class FakeContext:
        defaultParallelism = 12
        def __init__(self):
            self.broadcasts, self.waves = [], []
        def broadcast(self, value):
            item = FakeBroadcast(value)
            self.broadcasts.append(item)
            return item
        def parallelize(self, data, partitions):
            self.waves.append(data)
            return FakeRDD(data)

    class PoolTests(unittest.TestCase):
        def test_waves_order_single_task_and_broadcast_cleanup(self):
            from types import SimpleNamespace
            context = FakeContext()
            pool = namespace['SparkParallel'](SimpleNamespace(sparkContext=context), executor_processes=2)
            pool.executors = lambda: 3
            with patch.dict(namespace, {'Broadcast': FakeBroadcast, '_fork_available': lambda: False}):
                factor = [7]
                result = pool.map(namespace['_pool_task'], range(19), {'factor': factor, 'alias': factor})
                self.assertEqual(result, [(i*7, True) for i in range(19)])
                self.assertTrue(all(len(g) <= 2 for wave in context.waves for g in wave))
                self.assertTrue(all(sum(map(len, wave)) <= 6 for wave in context.waves))
                self.assertEqual(pool.map(namespace['_pool_task'], [3], {'factor': [2]}), [(6, True)])
            self.assertEqual(pool._bc, {})
            self.assertTrue(all(b.destroyed for b in context.broadcasts))

        def test_exception_releases_broadcasts(self):
            from types import SimpleNamespace
            context = FakeContext()
            pool = namespace['SparkParallel'](SimpleNamespace(sparkContext=context))
            with patch.dict(namespace, {'Broadcast': FakeBroadcast, '_fork_available': lambda: False}):
                with self.assertRaises(ValueError):
                    pool.map(namespace['_pool_task'], [-1], {'factor': [3]})
            self.assertEqual(pool._bc, {})
            self.assertTrue(all(b.destroyed for b in context.broadcasts))
    return unittest.defaultTestLoader.loadTestsFromTestCase(PoolTests)


def main():
    os.chdir(HERE)
    namespace = load_definitions()
    with tempfile.TemporaryDirectory(prefix="spark_v2_validation_") as work:
        namespace["SELFTEST_TMP"] = work
        cfg = namespace["make_config"]("selftest", root=work, out_root=work,
                                       random_pairs=150_000, dedup_random_pairs=150_000,
                                       sim_records=4_000, chunk_size=700, bootstrap_reps=40,
                                       self_check=False)
        namespace["_T"]["cfg"] = cfg
        namespace["_T"]["maps"] = namespace["load_mappings"](HERE / "mappings")
        namespace["_T"]["ref"] = namespace["load_reference"](HERE / "reference", cfg.core)
        namespace["CFG"] = cfg
        namespace["PAR"] = namespace["Parallel"](1, pairs_per_task=100_000)
        pool_result = unittest.TextTestRunner(verbosity=2, failfast=True).run(pool_suite(namespace))
        if not pool_result.wasSuccessful():
            return 1
        if "--full" in sys.argv:
            result, text = namespace["run_selftests"](verbosity=2)
            print(text)
        else:
            suite = unittest.TestSuite()
            for name in ("TestSparkV2Memory", "TestParallel", "TestEMBootstrap"):
                suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(namespace[name]))
            result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
        print(f"Parsed every code cell; ran {result.testsRun} tests, {len(result.skipped)} skipped")
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
